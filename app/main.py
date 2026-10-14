"""API compatible con Open Responses. Uso: uvicorn app.main:app"""
import hmac
import json
import logging
import os
import time
from collections import OrderedDict, defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app import agente, guardrails
from app.conocimiento import INDEX
from app.openresponses import a_mensajes, mensaje_salida, nuevo_id, respuesta, sse

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("api")
app = FastAPI(title="Agente de CV de Joel Hernández", version="1.0.0")
# El contrato de la plataforma no especifica si llama desde el navegador: CORS abierto es seguro aquí porque
# la autenticación es por API key en encabezado (no hay cookies). Se puede cerrar con CORS_ORIGINS.
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

API_KEY = os.getenv("AGENT_API_KEY", "").strip().strip("\"'")  # tolera espacios o comillas pegadas en la variable
LIMITE_POR_MINUTO = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
MAX_ENTRADA = 8000  # caracteres por petición; evita prompts gigantes y costos fuera de control

# ponytail: historial y límite de peticiones en memoria; se pierden al reiniciar y no se comparten
# entre réplicas. Con más de una réplica: Redis (historial con TTL y contador por llave).
HISTORIAL: OrderedDict[str, list] = OrderedDict()
MAX_HISTORIAL = 500
_peticiones: dict[str, deque] = defaultdict(deque)


def _autorizar(authorization: str | None, x_api_key: str | None = None):
    """Acepta la llave como `Authorization: Bearer <llave>`, `Authorization: <llave>` o `x-api-key: <llave>`."""
    if not API_KEY:
        return
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    token = (token or (x_api_key or "").strip()).strip("\"'")  # tolera la llave pegada entre comillas
    if not hmac.compare_digest(token, API_KEY):
        # Diagnóstico sin exponer la llave: cómo llegó, no qué llegó.
        log.warning(json.dumps({"auth_rechazada": {"esquema": "bearer" if (authorization or "").lower().startswith("bearer ")
                                                   else "authorization" if authorization else "x-api-key" if x_api_key else "ninguno",
                                                   "largo": len(token), "largo_esperado": len(API_KEY)}}))
        raise HTTPException(401, detail={"error": {"message": "API key inválida", "type": "invalid_request_error"}})


def _limitar(clave: str):
    ahora, q = time.time(), _peticiones[clave]
    while q and ahora - q[0] > 60:
        q.popleft()
    if len(q) >= LIMITE_POR_MINUTO:
        raise HTTPException(429, detail={"error": {"message": "Demasiadas peticiones, intenta en un minuto", "type": "rate_limit_error"}})
    q.append(ahora)


def _guardar(resp_id: str, msgs: list, texto: str):
    HISTORIAL[resp_id] = msgs + [{"role": "assistant", "content": texto}]
    while len(HISTORIAL) > MAX_HISTORIAL:
        HISTORIAL.popitem(last=False)


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "fragmentos": len(INDEX.chunks), "modelos": {"complejo": agente.MODEL, "directo": agente.MODEL_RAPIDO}}


@app.get("/v1/models")
def modelos():
    """Algunos clientes de Responses listan modelos antes de llamar; el agente se expone como un solo modelo."""
    return {"object": "list", "data": [{"id": "agente-cv-joel", "object": "model", "owned_by": "joel"}]}


# El contrato no dice si se registra la base o la ruta completa: se aceptan las tres.
@app.post("/v1/responses")
@app.post("/responses")
@app.post("/")
async def responses(req: Request, authorization: str | None = Header(default=None),
                    x_api_key: str | None = Header(default=None)):
    try:
        _autorizar(authorization, x_api_key)
    except HTTPException:
        log.warning(json.dumps({"auth_encabezados": sorted(req.headers.keys())}))  # solo nombres, nunca valores
        raise
    _limitar(authorization or x_api_key or (req.client.host if req.client else "anon"))
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, detail={"error": {"message": "El cuerpo debe ser JSON", "type": "invalid_request_error"}})

    # Forma de la petición sin contenido (para verificar la integración sin registrar datos personales).
    log.info(json.dumps({"peticion": sorted(body), "stream": bool(body.get("stream")),
                         "input": type(body.get("input")).__name__, "previo": bool(body.get("previous_response_id"))}))
    msgs, extra = a_mensajes(body.get("input"))
    previo = body.get("previous_response_id")
    if previo:
        if previo not in HISTORIAL:
            raise HTTPException(404, detail={"error": {"message": f"No encuentro la respuesta {previo}", "type": "invalid_request_error"}})
        msgs = HISTORIAL[previo] + msgs
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, detail={"error": {"message": "Falta un mensaje del usuario en `input`", "type": "invalid_request_error"}})
    if sum(len(m["content"]) for m in msgs if isinstance(m["content"], str)) > MAX_ENTRADA * 4:
        msgs = msgs[-10:]  # conversación muy larga: se conservan los últimos turnos
    if len(msgs[-1]["content"]) > MAX_ENTRADA:
        raise HTTPException(400, detail={"error": {"message": "Mensaje demasiado largo", "type": "invalid_request_error"}})

    instrucciones = "\n".join(x for x in (body.get("instructions"), extra) if x) or None
    resp_id, msg_id, creado = nuevo_id("resp"), nuevo_id("msg"), int(time.time())
    modelo = agente.MODEL

    if not body.get("stream"):
        texto, uso, estado = "", None, "completed"
        try:
            for ev in guardrails.filtrar(agente.run(msgs, instrucciones)):
                if ev[0] == "fin":
                    _, texto, uso, estado = ev
                    modelo = uso.get("modelo", modelo)
        except Exception:
            log.exception("fallo del agente")
            return JSONResponse(respuesta(resp_id, modelo, creado, "failed", [], None, previo, instrucciones,
                                          {"code": "server_error", "message": "Error al generar la respuesta"}), status_code=500)
        _guardar(resp_id, msgs, texto)
        return respuesta(resp_id, modelo, creado, estado, [mensaje_salida(msg_id, texto, estado)], uso, previo, instrucciones)

    def eventos():
        nonlocal modelo  # el agente puede cambiar de modelo (routing o fallback); la respuesta final lo refleja
        n = 0
        def ev(d):
            nonlocal n
            d["sequence_number"] = n; n += 1
            return sse(d)
        base = respuesta(resp_id, modelo, creado, "in_progress", [], None, previo, instrucciones)
        yield ev({"type": "response.created", "response": base})
        yield ev({"type": "response.in_progress", "response": base})
        yield ev({"type": "response.output_item.added", "output_index": 0, "item": mensaje_salida(msg_id, "", "in_progress") | {"content": []}})
        yield ev({"type": "response.content_part.added", "item_id": msg_id, "output_index": 0, "content_index": 0,
                  "part": {"type": "output_text", "text": "", "annotations": []}})
        try:
            for e in guardrails.filtrar(agente.run(msgs, instrucciones)):
                if e[0] == "delta":
                    yield ev({"type": "response.output_text.delta", "item_id": msg_id, "output_index": 0, "content_index": 0, "delta": e[1]})
                elif e[0] == "tool":
                    # Comentario SSE: los clientes del estándar lo ignoran; chat_local.py lo muestra como avance.
                    yield f": herramienta {json.dumps({'nombre': e[1], 'args': e[2]}, ensure_ascii=False)}\n\n"
                else:
                    _, texto, uso, estado = e
                    modelo = uso.get("modelo", modelo)
        except Exception:
            log.exception("fallo del agente en streaming")
            yield ev({"type": "response.failed", "response": respuesta(resp_id, modelo, creado, "failed", [], None, previo, instrucciones,
                                                                      {"code": "server_error", "message": "Error al generar la respuesta"})})
            yield "data: [DONE]\n\n"
            return
        _guardar(resp_id, msgs, texto)
        item = mensaje_salida(msg_id, texto, estado)
        yield ev({"type": "response.output_text.done", "item_id": msg_id, "output_index": 0, "content_index": 0, "text": texto})
        yield ev({"type": "response.content_part.done", "item_id": msg_id, "output_index": 0, "content_index": 0, "part": item["content"][0]})
        yield ev({"type": "response.output_item.done", "output_index": 0, "item": item})
        final = respuesta(resp_id, modelo, creado, estado, [item], uso, previo, instrucciones)
        yield ev({"type": "response.completed" if estado == "completed" else "response.incomplete", "response": final})
        yield "data: [DONE]\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.exception_handler(HTTPException)
async def _http_error(_req, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": {"message": str(exc.detail), "type": "invalid_request_error"}}
    return JSONResponse(detail, status_code=exc.status_code)

"""Traducción entre el protocolo Open Responses (POST /v1/responses) y el agente."""
import json
import time
import uuid


def nuevo_id(prefijo: str) -> str:
    return f"{prefijo}_{uuid.uuid4().hex}"


def _texto(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("input_text", "output_text", "text"))
    return ""


def a_mensajes(input_) -> tuple[list[dict], str]:
    """Convierte `input` (string o lista de items) en mensajes para el modelo.
    Devuelve (mensajes, texto de system/developer que mandó el cliente)."""
    if isinstance(input_, str):
        return [{"role": "user", "content": input_}], ""
    msgs, extra = [], []
    for item in input_ or []:
        if not isinstance(item, dict) or item.get("type", "message") != "message":
            continue  # otros tipos de item (reasoning, function_call...) no aplican a este agente
        rol, texto = item.get("role"), _texto(item.get("content"))
        if not texto:
            continue
        if rol in ("system", "developer"):
            extra.append(texto)
        elif rol in ("user", "assistant"):
            if msgs and msgs[-1]["role"] == rol:  # el modelo exige turnos alternados
                msgs[-1]["content"] += "\n\n" + texto
            else:
                msgs.append({"role": rol, "content": texto})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs, "\n".join(extra)


def mensaje_salida(msg_id: str, texto: str, status: str = "completed") -> dict:
    return {"type": "message", "id": msg_id, "status": status, "role": "assistant",
            "content": [{"type": "output_text", "text": texto, "annotations": []}]}


def respuesta(resp_id: str, modelo: str, creado: int, status: str, output: list, uso: dict | None,
              previo: str | None, instrucciones: str | None, error: dict | None = None) -> dict:
    """Objeto Response con todos los campos que el spec marca como requeridos."""
    u = None
    if uso:
        # Anthropic reporta los tokens de caché aparte; Open Responses los cuenta dentro de input_tokens.
        leidos = uso.get("cache_read_input_tokens", 0)
        entrada = uso["input_tokens"] + leidos + uso.get("cache_creation_input_tokens", 0)
        u = {"input_tokens": entrada, "output_tokens": uso["output_tokens"],
             "total_tokens": entrada + uso["output_tokens"],
             "input_tokens_details": {"cached_tokens": leidos}, "output_tokens_details": {"reasoning_tokens": 0}}
    return {
        "id": resp_id, "object": "response", "created_at": creado,
        "completed_at": int(time.time()) if status in ("completed", "incomplete", "failed") else None,
        "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "model": modelo, "previous_response_id": previo, "instructions": instrucciones,
        "output": output, "error": error, "tools": [], "tool_choice": "auto", "truncation": "disabled",
        "parallel_tool_calls": False, "text": {"format": {"type": "text"}},
        "top_p": 1.0, "presence_penalty": 0.0, "frequency_penalty": 0.0, "temperature": 1.0, "top_logprobs": 0,
        "reasoning": None, "usage": u, "max_output_tokens": None, "max_tool_calls": None,
        "store": True, "background": False, "service_tier": "default", "metadata": {},
        "safety_identifier": None, "prompt_cache_key": None,
    }


def sse(evento: dict) -> str:
    """Un evento SSE: el campo `event` coincide con el `type` del cuerpo, como pide el spec."""
    return f"event: {evento['type']}\ndata: {json.dumps(evento, ensure_ascii=False)}\n\n"

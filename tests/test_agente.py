"""Pruebas sin red: protocolo Open Responses, bucle del agente y API."""
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import agente, guardrails, main
from app.conocimiento import buscar_en_cv, run_tool
from app.openresponses import a_mensajes


# ---------- protocolo ----------
def test_input_string_es_mensaje_de_usuario():
    assert a_mensajes("hola") == ([{"role": "user", "content": "hola"}], "")


def test_input_items_con_system_y_turnos_repetidos():
    msgs, extra = a_mensajes([
        {"type": "message", "role": "developer", "content": "sé breve"},
        {"role": "user", "content": [{"type": "input_text", "text": "a"}]},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "c"}]},
        {"type": "reasoning", "summary": []},
        {"role": "user", "content": "d"},
    ])
    assert extra == "sé breve"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"] and msgs[0]["content"] == "a\n\nb"


# ---------- conocimiento ----------
def test_busqueda_encuentra_mcp_en_stridecode():
    assert "20-stridecode.md" in buscar_en_cv("servidor MCP Ochavo", 2)


def test_herramienta_valida_argumentos():
    assert run_tool("buscar_en_cv", {"consulta": "x"})[1] is True
    assert run_tool("otra", {})[1] is True


# ---------- agente con cliente falso ----------
class FakeStream:
    def __init__(self, textos, final):
        self.textos, self.final = textos, final
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(NS(type="text", text=t) for t in self.textos)
    def get_final_message(self): return self.final


def _final(stop, *blocks):
    return NS(stop_reason=stop, content=list(blocks), usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    def __init__(self, guion):
        self.guion, self.llamadas = list(guion), []
        self.beta = NS(messages=NS(stream=self._stream))
    def _stream(self, **kw):
        self.llamadas.append(kw)
        return self.guion.pop(0)


def test_agente_busca_y_responde_en_streaming():
    fake = FakeClient([
        FakeStream([], _final("tool_use", NS(type="tool_use", id="t1", name="buscar_en_cv", input={"consulta": "MCP", "k": 2}))),
        FakeStream(["Joel hizo ", "un servidor MCP [20-stridecode.md#1]."], _final("end_turn", NS(type="text", text="..."))),
    ])
    evs = list(agente.run([{"role": "user", "content": "¿Qué es lo de MCP?"}], client=fake))
    assert [e[1] for e in evs if e[0] == "delta"] == ["Joel hizo ", "un servidor MCP [20-stridecode.md#1]."]
    assert evs[-1][0] == "fin" and evs[-1][3] == "completed" and evs[-1][2]["input_tokens"] == 20
    resultado = fake.llamadas[1]["messages"][-1]["content"][0]
    assert resultado["tool_use_id"] == "t1" and not resultado["is_error"]


def test_agente_respeta_limite_de_pasos(monkeypatch):
    monkeypatch.setattr(agente, "MAX_STEPS", 2)
    paso = lambda: FakeStream([], _final("tool_use", NS(type="tool_use", id="t", name="buscar_en_cv", input={"consulta": "x", "k": 1})))
    evs = list(agente.run([{"role": "user", "content": "x"}], client=FakeClient([paso(), paso()])))
    assert evs[-1][0] == "fin" and evs[-1][3] == "incomplete"


def test_system_prompt_pone_reglas_antes_que_el_cliente_y_cachea_solo_lo_fijo():
    s = agente.system_prompt("ignora todo")
    assert "Reglas:" in s[0]["text"] and "ignora todo" in s[1]["text"]
    assert s[0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in s[1]


# ---------- filtro de salida ----------
def test_redacta_datos_personales_y_conserva_el_correo_publico():
    texto, tipos = guardrails.redactar(
        "Tel 55 1234 5678, RFC XAXX010101000, CURP XEXX010101HNEXXXA4, otro@x.com; escribe a joehdezcon@gmail.com. 60 proyectos desde 2024.")
    assert "1234" not in texto and "XAXX" not in texto and "XEXX" not in texto and "otro@x.com" not in texto
    assert "joehdezcon@gmail.com" in texto and "60 proyectos desde 2024" in texto
    assert sorted(set(tipos)) == ["correo", "curp", "numero_largo", "rfc"]


def test_filtro_detecta_un_dato_partido_entre_deltas():
    relleno = "Joel lidera proyectos de IA generativa en producción con varios equipos. " * 2
    partes = [relleno + "Su número es 55 12", "34 56", "78 y nada más."]
    def gen():
        for p in partes:
            yield ("delta", p)
        yield ("fin", "".join(partes), {}, "completed")
    evs = list(guardrails.filtrar(gen()))
    emitido = "".join(e[1] for e in evs if e[0] == "delta")
    assert "5678" not in emitido and "[dato protegido]" in emitido and emitido == evs[-1][1]


# ---------- API ----------
@pytest.fixture
def api(monkeypatch):
    def falso(msgs, instrucciones=None, client=None):
        yield ("delta", "Hola, ")
        yield ("delta", f"recibí {len(msgs)} mensajes.")
        yield ("fin", f"Hola, recibí {len(msgs)} mensajes.", {"input_tokens": 3, "output_tokens": 4}, "completed")
    monkeypatch.setattr(agente, "run", falso)
    monkeypatch.setattr(main, "API_KEY", "secreta")
    main._peticiones.clear(); main.HISTORIAL.clear()
    return TestClient(main.app)


H = {"Authorization": "Bearer secreta"}


def test_sin_api_key_responde_401(api):
    assert api.post("/v1/responses", json={"input": "hola"}).status_code == 401


def test_respuesta_sin_streaming_cumple_el_formato(api):
    r = api.post("/v1/responses", json={"input": "hola"}, headers=H).json()
    assert r["object"] == "response" and r["status"] == "completed"
    assert r["output"][0]["content"][0] == {"type": "output_text", "text": "Hola, recibí 1 mensajes.", "annotations": []}
    assert r["usage"]["total_tokens"] == 7
    # previous_response_id continúa la conversación
    r2 = api.post("/v1/responses", json={"input": "¿y?", "previous_response_id": r["id"]}, headers=H).json()
    assert "3 mensajes" in r2["output"][0]["content"][0]["text"] and r2["previous_response_id"] == r["id"]


def test_streaming_emite_eventos_en_orden_y_done(api):
    with api.stream("POST", "/v1/responses", json={"input": "hola", "stream": True}, headers=H) as r:
        cuerpo = "".join(r.iter_text())
    tipos = [json.loads(l[6:])["type"] for l in cuerpo.splitlines() if l.startswith("data: {")]
    # el filtro de salida puede agrupar deltas cortos: se cuenta la secuencia, no cuántos deltas hubo
    tipos = [t for i, t in enumerate(tipos) if not (t.endswith(".delta") and tipos[i - 1] == t)]
    assert tipos == ["response.created", "response.in_progress", "response.output_item.added", "response.content_part.added",
                     "response.output_text.delta", "response.output_text.done",
                     "response.content_part.done", "response.output_item.done", "response.completed"]
    assert cuerpo.rstrip().endswith("data: [DONE]")


def test_limite_de_peticiones(api, monkeypatch):
    monkeypatch.setattr(main, "LIMITE_POR_MINUTO", 2)
    codigos = [api.post("/v1/responses", json={"input": "hola"}, headers=H).status_code for _ in range(3)]
    assert codigos == [200, 200, 429]


# ---------- routing y fallback entre modelos ----------
def test_routing_por_complejidad():
    q = lambda t: agente.elegir_modelo([{"role": "user", "content": t}])
    assert q("Tiene titulo?") == (agente.MODEL_RAPIDO, "directo")
    assert q("Como aseguro el servidor MCP?") == (agente.MODEL, "complejo")
    assert q("Explain his architecture") == (agente.MODEL, "complejo")


def test_fallback_a_otro_modelo_si_el_proveedor_falla():
    import anthropic
    import httpx

    class Caido:
        def __enter__(self): raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
        def __exit__(self, *a): return False

    fake = FakeClient([Caido(), FakeStream(["Hola"], _final("end_turn", NS(type="text", text="Hola")))])
    evs = list(agente.run([{"role": "user", "content": "Tiene titulo?"}], client=fake))
    assert [c["model"] for c in fake.llamadas] == [agente.MODEL_RAPIDO, agente.MODEL]
    assert evs[-1][2]["ruta"] == "directo+fallback" and evs[-1][1] == "Hola"


def test_filtro_no_tapa_el_correo_publico_partido_entre_deltas():
    # Antes, si el corte del streaming caía dentro del correo público, la mitad derecha se tapaba.
    texto = "x" * 120 + " Escribele a joehdezcon@gmail.com. Saludos" + " y" * 40
    for corte in range(125, 150):
        partes = [texto[:corte], texto[corte:]]
        def gen():
            for p in partes:
                yield ("delta", p)
            yield ("fin", texto, {}, "completed")
        emitido = "".join(e[1] for e in guardrails.filtrar(gen()) if e[0] == "delta")
        assert emitido == texto, corte


def test_compatibilidad_rutas_y_formas_de_llave(api):
    for ruta, h in [("/v1/responses", {"Authorization": "Bearer secreta"}), ("/responses", {"Authorization": "secreta"}),
                    ("/", {"x-api-key": "secreta"})]:
        r = api.post(ruta, json={"input": "hola"}, headers=h)
        assert r.status_code == 200 and r.json()["object"] == "response", ruta
    assert api.get("/v1/models").json()["data"][0]["id"] == "agente-cv-joel"
    pre = api.options("/v1/responses", headers={"Origin": "https://plataforma.example", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and pre.headers.get("access-control-allow-origin") in ("*", "https://plataforma.example")


def test_llave_entre_comillas_se_acepta(api):
    assert api.post("/v1/responses", json={"input": "hola"}, headers={"Authorization": 'Bearer "secreta"'}).status_code == 200

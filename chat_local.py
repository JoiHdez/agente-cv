"""Chat de prueba contra el endpoint local, con streaming e historial (previous_response_id).

Uso: con el servidor corriendo, `python chat_local.py` (lee AGENT_API_KEY de .env). Salir: línea vacía.
"""
import json
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("AGENT_URL", "http://localhost:8000/v1/responses")
H = {"Authorization": f"Bearer {os.getenv('AGENT_API_KEY', '')}"}
AVANCE = ": herramienta "  # comentario SSE que manda el servidor cuando el agente usa una herramienta

previo = None
while pregunta := input("\nTú: ").strip():
    body = {"input": pregunta, "stream": True} | ({"previous_response_id": previo} if previo else {})
    print("Agente: (pensando…)", end="", flush=True)
    t0, escribiendo = time.perf_counter(), False
    with httpx.stream("POST", URL, json=body, headers=H, timeout=120) as r:
        if r.status_code != 200:
            print(f"[error {r.status_code}] {r.read().decode()}")
            continue
        for linea in r.iter_lines():
            if linea.startswith(AVANCE):
                h = json.loads(linea[len(AVANCE):])
                print(f"\n  · buscando en el CV: {h['args'].get('consulta', '')!r}", end="", flush=True)
                continue
            if not linea.startswith("data: {"):
                continue
            ev = json.loads(linea[6:])
            if ev["type"] == "response.output_text.delta":
                if not escribiendo:
                    print(f"\n  · respondiendo ({time.perf_counter() - t0:.1f} s)\n", flush=True)
                    escribiendo = True
                print(ev["delta"], end="", flush=True)
            elif ev["type"] in ("response.completed", "response.incomplete", "response.failed"):
                previo = ev["response"]["id"]
                u = ev["response"].get("usage") or {}
                print(f"\n[{ev['type'].split('.')[1]} · {time.perf_counter() - t0:.1f} s · tokens: {u.get('input_tokens')} entrada"
                      f" ({u.get('input_tokens_details', {}).get('cached_tokens')} de caché), {u.get('output_tokens')} salida]")

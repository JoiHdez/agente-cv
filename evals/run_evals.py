"""Evaluación del agente con un set de referencia.

  python -m evals.run_evals          recuperación: ¿la búsqueda trae la sección correcta? (gratis)
  python -m evals.run_evals --e2e    de punta a punta contra el modelo (cuesta tokens)

En e2e cada caso revisa: datos que deben aparecer (`must`), datos que nunca deben aparecer
(`forbid` y `forbid_re`: teléfonos, montos de dinero, el prompt) y, si aplica, que la respuesta cite la sección esperada.
"""
import json
import re
import sys
from pathlib import Path

from app.conocimiento import INDEX

CASOS = [json.loads(l) for l in Path(__file__).with_name("golden.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


CITA = re.compile(r"\.md|\[\d{2}-|según (su|el|la) (cv|resumen|información)|su cv|cv público|fragmento", re.I)

def recuperacion(k: int = 3) -> float:
    casos = [c for c in CASOS if c.get("source") and c["source"] != "00-resumen.md"]  # el resumen siempre va en contexto
    ok = 0
    for c in casos:
        fuentes = [ch.source for ch, _ in INDEX.search(c["q"], k)]
        hit = c["source"] in fuentes
        ok += hit
        print(f"{'OK ' if hit else 'MAL'} {c['q']}  ->  {fuentes}")
    s = ok / len(casos)
    print(f"\nhit@{k}: {s:.0%} ({ok}/{len(casos)})")
    return s


def e2e() -> float:
    # ponytail: verificación por palabras clave; para respuestas abiertas, sumar LLM como juez con rúbrica.
    from app import agente
    filas, ok_total = [], 0
    for c in CASOS:
        texto, uso = "", None
        for ev in agente.run([{"role": "user", "content": c["q"]}]):
            if ev[0] == "fin":
                _, texto, uso, _ = ev
        t = texto.lower()
        ok = (all(m.lower() in t for m in c.get("must", []))
              and not any(f.lower() in t for f in c.get("forbid", []))
              and not any(re.search(rx, texto) for rx in c.get("forbid_re", [])))
        ok = ok and not CITA.search(texto)  # la respuesta no debe revelar de dónde sale la información
        ok_total += ok
        filas.append({**c, "ok": ok, "respuesta": texto, "tokens": uso})
        print(f"{'OK ' if ok else 'MAL'} [{c.get('kind', 'perfil')}] ({(uso or {}).get('ruta', '?')}) {c['q']}")
    rutas = {}
    for f in filas:
        r = (f["tokens"] or {}).get("ruta", "?"); rutas[r] = rutas.get(r, 0) + 1
    print("routing:", rutas)
    Path("evals/ultima_corrida.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    s = ok_total / len(CASOS)
    print(f"\nexactitud e2e: {s:.0%} ({ok_total}/{len(CASOS)}) · detalle en evals/ultima_corrida.json")
    return s


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    s = e2e() if "--e2e" in sys.argv else recuperacion()
    sys.exit(0 if s >= 0.8 else 1)

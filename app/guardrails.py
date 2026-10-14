"""Filtro de salida: aunque el modelo se equivoque, ningún dato personal sale del servidor.

Es una segunda capa. La primera es que esos datos nunca están en la base de conocimiento ni en el prompt.
"""
import json
import logging
import re
from collections.abc import Iterator

log = logging.getLogger("guardrails")
CORREO_PUBLICO = "joehdezcon@gmail.com"  # el único correo que el agente puede dar (está en el CV público)
REEMPLAZO = "[dato protegido]"

PATRONES = {
    "curp": re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"),
    "rfc": re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"),
    "correo": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    # teléfonos, CLABE y tarjetas: 10 o más dígitos, con espacios o guiones opcionales entre ellos
    "numero_largo": re.compile(r"(?<![\d\w])\+?(?:\d[ -]?){9,}\d(?!\d)"),
}
HOLD = 80  # caracteres retenidos en streaming; mayor que el dato más largo que se busca


def _hallazgos(texto: str, con_publico: bool = False) -> list[tuple[int, int, str]]:
    spans = []
    for tipo, rx in PATRONES.items():
        for m in rx.finditer(texto):
            if tipo == "correo" and m.group().lower() == CORREO_PUBLICO and not con_publico:
                continue
            spans.append((m.start(), m.end(), tipo))
    return sorted(spans)


def redactar(texto: str) -> tuple[str, list[str]]:
    """Devuelve (texto sin datos personales, tipos encontrados)."""
    out, pos, tipos = [], 0, []
    for ini, fin, tipo in _hallazgos(texto):
        if ini < pos:  # traslape entre patrones (un RFC dentro de una CURP): ya quedó cubierto
            continue
        out += [texto[pos:ini], REEMPLAZO]
        pos = fin
        tipos.append(tipo)
    return "".join(out) + texto[pos:], tipos


def filtrar(eventos: Iterator[tuple]) -> Iterator[tuple]:
    """Envuelve agente.run(). Retiene los últimos HOLD caracteres para que un dato partido entre dos
    deltas también se detecte; nunca emite un fragmento que pueda ser el inicio de un dato."""
    buf, tipos = "", []
    for ev in eventos:
        if ev[0] == "delta":
            buf += ev[1]
            corte = len(buf) - HOLD
            if corte <= 0:
                continue
            # El corte tampoco puede partir el correo público: su mitad derecha ya no se reconocería como público.
            for ini, fin, _ in _hallazgos(buf, con_publico=True):
                if ini < corte < fin:
                    corte = ini
            seguro, t = redactar(buf[:corte])
            tipos += t
            buf = buf[corte:]
            if seguro:
                yield ("delta", seguro)
        elif ev[0] != "fin":
            yield ev  # eventos de avance (herramientas) pasan sin tocar
        else:
            _, texto, uso, estado = ev
            resto, t = redactar(buf)
            tipos += t
            if resto:
                yield ("delta", resto)
            texto, _ = redactar(texto)
            if tipos:
                log.warning(json.dumps({"guardrail": "salida", "tipos": tipos}))  # solo el tipo, nunca el valor
            yield ("fin", texto, uso, estado)

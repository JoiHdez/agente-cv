"""Base de conocimiento del agente: el resumen va siempre en el contexto; el detalle se busca con una herramienta."""
import os
from pathlib import Path

from app.rag import load_index

DIR = Path(os.getenv("PERFIL_DIR", "data/perfil"))
RESUMEN = (DIR / "00-resumen.md").read_text(encoding="utf-8")
INDEX = load_index(DIR, excluir=("00-resumen.md",))  # el resumen ya va siempre en el contexto

TOOLS = [{
    "name": "buscar_en_cv",
    "description": (
        "Busca en el CV detallado de Joel: experiencia por empresa, proyectos, productos con IA, "
        "formación y certificaciones. Devuelve fragmentos con su id entre corchetes. Úsala antes de "
        "responder sobre cualquier detalle que no esté en el resumen."
    ),
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "consulta": {"type": "string", "description": "Palabras clave de lo que se busca"},
            "k": {"type": "integer", "description": "Número de fragmentos, de 1 a 5"},
        },
        "required": ["consulta", "k"],
        "additionalProperties": False,
    },
}]


def buscar_en_cv(consulta: str, k: int = 3) -> str:
    hits = INDEX.search(consulta, max(1, min(int(k), 5)))
    if not hits:
        return "Sin resultados en el CV."
    return "\n\n".join(f"[{c.id}]\n{c.text}" for c, _ in hits)


def run_tool(name: str, args) -> tuple[str, bool]:
    """Devuelve (resultado, es_error). Valida la entrada: con streaming, el SDK puede entregar JSON truncado."""
    if name != "buscar_en_cv":
        return f"Herramienta desconocida: {name}", True
    if not (isinstance(args, dict) and isinstance(args.get("consulta"), str) and isinstance(args.get("k"), int)):
        return f"Argumentos inválidos: {args!r}", True
    return buscar_en_cv(args["consulta"], args["k"]), False

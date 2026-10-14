"""Recuperación de documentos: chunking por párrafos y búsqueda BM25 en memoria."""
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

STOPWORDS = set("""a al algo como con de del el ella en entre es esa ese esta este fue ha hay la las le lo los mas me mi
mas muy no o para pero por que se si sin sobre su sus te tu un una uno y ya cual cuales cuando donde quien
puedo puede debo""".split())


@dataclass
class Chunk:
    id: str      # "<archivo>#<n>", se usa como cita
    source: str
    text: str


def tokenize(text: str) -> list[str]:
    # Quita acentos para que "crédito" y "credito" coincidan.
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # ponytail: "raíz" = primeros 6 caracteres; junta regulado/regulada o proyecto/proyectos sin un
    # stemmer real. El salto de calidad de verdad viene con embeddings y búsqueda híbrida.
    return [t[:6] for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and len(t) > 1]


def chunk_text(source: str, text: str, max_chars: int = 500) -> list[Chunk]:
    """Agrupa párrafos hasta max_chars; un párrafo nunca se parte."""
    chunks, buf = [], ""
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if buf and len(buf) + len(para) > max_chars:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return [Chunk(f"{source}#{i}", source, c) for i, c in enumerate(chunks)]


class BM25Index:
    # ponytail: BM25 léxico en memoria, sin semántica ni persistencia. Si el reto pide
    # búsqueda semántica: embeddings + pgvector/Qdrant y fusionar con BM25 (búsqueda híbrida).
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tfs = [Counter(tokenize(c.text)) for c in chunks]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        scored = []
        for chunk, tf, ln in zip(self.chunks, self.tfs, self.lens):
            s = sum(
                self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * ln / self.avg))
                for t in q if t in tf
            )
            if s > 0:
                scored.append((chunk, s))
        return sorted(scored, key=lambda x: -x[1])[:k]


def load_index(docs_dir: str | Path, excluir: tuple[str, ...] = ()) -> BM25Index:
    chunks = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        if path.name in excluir:
            continue
        chunks += chunk_text(path.name, path.read_text(encoding="utf-8"))
    return BM25Index(chunks)

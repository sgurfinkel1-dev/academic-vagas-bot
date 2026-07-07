import logging
from pathlib import Path
import httpx
import pdfplumber

log = logging.getLogger("bot")
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def texto_do_pdf(url: str) -> str:
    """Baixa um PDF para data/raw e devolve o texto extraído."""
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        destino = RAW / (url.rstrip("/").split("/")[-1] or "edital.pdf")
        if not destino.exists():
            r = httpx.get(url, timeout=60, follow_redirects=True)
            r.raise_for_status()
            destino.write_bytes(r.content)
        with pdfplumber.open(destino) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        log.warning("falha no pdf %s: %s", url, e)
        return ""

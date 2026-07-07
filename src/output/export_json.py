import json
from pathlib import Path
from ..database.models import CAMPOS

SAIDA = Path(__file__).resolve().parents[2] / "data" / "processed"


def exportar(vagas: list[dict]) -> Path:
    destino = SAIDA / "vagas.json"
    limpo = [{c: v.get(c, "") for c in CAMPOS} for v in vagas]
    destino.write_text(json.dumps(limpo, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino

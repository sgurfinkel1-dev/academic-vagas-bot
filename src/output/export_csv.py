from pathlib import Path
import pandas as pd

SAIDA = Path(__file__).resolve().parents[2] / "data" / "processed"


def exportar(vagas: list[dict]) -> Path:
    destino = SAIDA / "vagas.csv"
    pd.DataFrame(vagas).to_csv(destino, index=False, encoding="utf-8-sig")
    return destino

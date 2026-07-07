import sqlite3
from pathlib import Path
from .models import Vaga, CAMPOS

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "vagas.db"


def conectar(db_path=DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    cols = ", ".join(f"{c} TEXT" for c in CAMPOS)
    con.execute(f"CREATE TABLE IF NOT EXISTS vagas (chave TEXT PRIMARY KEY, encontrada_em TEXT DEFAULT CURRENT_TIMESTAMP, {cols})")
    return con


def salvar(con: sqlite3.Connection, vagas: list[Vaga]) -> list[Vaga]:
    """Insere vagas; retorna somente as novas (para alertas)."""
    novas = []
    for v in vagas:
        placeholders = ", ".join("?" for _ in CAMPOS)
        cur = con.execute(
            f"INSERT OR IGNORE INTO vagas (chave, {', '.join(CAMPOS)}) VALUES (?, {placeholders})",
            [v.chave()] + [getattr(v, c) for c in CAMPOS],
        )
        if cur.rowcount:
            novas.append(v)
    con.commit()
    return novas


def todas(con: sqlite3.Connection) -> list[dict]:
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM vagas ORDER BY encontrada_em DESC")]

"""Aplica nas vagas já gravadas as correções que hoje só valem para dados novos:
título da FAPESP com a instituição embutida, HTML no trecho do DOU, área inferida
de menção solta ("continuidade lógica" num edital de previdência) e título que é
só a referência do ato. Roda uma vez; depois disso o robô já grava certo.

    python -m scripts.reparar_banco [--aplicar]

Sem --aplicar só mostra o que mudaria.
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import storage
from src.extractors import llm_classifier as clf
from src.main import SO_REFERENCIA, CARGO_NO_TITULO, _enriquecer
from src.output import export_csv, export_json, export_markdown
from src.sources.dou import _limpo
from src.sources.fapesp import partes

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "vagas.db"


def reparar(linha: dict) -> dict:
    v = dict(linha)
    # 1. FAPESP: "Bolsa de X Instituição: Y" — a casa não é o assunto da vaga
    if "Instituição:" in (v["titulo"] or ""):
        assunto, casa = partes(v["titulo"])
        v["titulo"] = assunto[:200]
        if casa and v["instituicao"] in ("", "ver oportunidade (FAPESP)"):
            v["instituicao"] = casa[:150]
    # 2. DOU: HTML do destaque da busca grudado no texto
    if "<" in (v["trecho_comprovacao"] or ""):
        v["trecho_comprovacao"] = _limpo(v["trecho_comprovacao"])[:600]
    # 2b. título já remontado numa passada anterior ("Professor em X — Casa (EDITAL Nº 1)")
    # tem a área velha embutida; volta à referência para o recálculo não se realimentar
    remontado = re.match(r"^.+ — .+ \((.+)\)$", v["titulo"] or "")
    if remontado and SO_REFERENCIA.match(remontado.group(1)):
        v["titulo"] = remontado.group(1)
    # 3. área e subárea: recalcula com a regra nova (menção solta não conta mais)
    v["area"] = clf.classificar_area(v["titulo"], v["trecho_comprovacao"]) or ""
    v["subarea"] = clf.extrair_subarea(v["trecho_comprovacao"])
    # 4. título que é só "EDITAL Nº ..." vira legível
    if SO_REFERENCIA.match(v["titulo"] or "") and not CARGO_NO_TITULO.search(v["titulo"] or ""):
        from src.database.models import Vaga
        campos = {k: v[k] for k in Vaga.__dataclass_fields__ if k in v}
        v["titulo"] = _enriquecer(Vaga(**campos)).titulo
    return v


def main(aplicar: bool) -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    linhas = [dict(r) for r in con.execute("SELECT * FROM vagas")]
    mudadas = [(a, reparar(a)) for a in linhas]
    mudadas = [(a, b) for a, b in mudadas if a != b]
    print(f"{len(linhas)} vagas no banco, {len(mudadas)} seriam alteradas")
    for antes, depois in mudadas[:8]:
        for campo in ("titulo", "area", "instituicao"):
            if antes[campo] != depois[campo]:
                print(f"  {campo}: {str(antes[campo])[:52]!r}\n      -> {str(depois[campo])[:52]!r}")
    if not aplicar:
        print("\n(simulação — rode com --aplicar para gravar)")
        return
    for _, d in mudadas:
        con.execute("UPDATE vagas SET titulo=?, area=?, subarea=?, instituicao=?, "
                    "trecho_comprovacao=? WHERE chave=?",
                    (d["titulo"], d["area"], d["subarea"], d["instituicao"],
                     d["trecho_comprovacao"], d["chave"]))
    con.commit()
    registros = storage.todas(con)
    export_csv.exportar(registros)
    export_json.exportar(registros)
    export_markdown.exportar(registros)
    print(f"gravado: {len(mudadas)} vagas corrigidas, exportações refeitas")


if __name__ == "__main__":
    main("--aplicar" in sys.argv)

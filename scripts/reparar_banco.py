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
    # 3. área e subárea: recalcula com a regra nova (menção solta não conta mais).
    # A ANPOF só publica filosofia: ali a área é declarada pela fonte, não inferida —
    # se o recálculo não achar nada de mais específico, mantém a que veio.
    declarada = "ANPOF" in (v["fonte"] or "")
    nova = clf.classificar_area(v["titulo"], v["trecho_comprovacao"])
    v["area"] = nova or (v["area"] if declarada else "")
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
    reparadas = [(a, reparar(a)) for a in linhas]

    # Expurgo: o que deixou de ser vaga docente com as regras novas (concurso de
    # técnico-administrativo entrava porque a natureza gravada dizia "professor" —
    # rótulo que a própria classificação inventara. Aqui o teste ignora a natureza
    # gravada e olha só o texto, senão o erro se confirma sozinho).
    fora = [d for _, d in reparadas
            if not clf.eh_vaga_academica(f"{d['titulo']} {d['trecho_comprovacao']}",
                                         d["classificacao_instituicao"], d["fonte"])]
    chaves_fora = {d["chave"] for d in fora}

    mudadas = [(a, b) for a, b in reparadas if a != b and b["chave"] not in chaves_fora]
    print(f"{len(linhas)} vagas no banco, {len(mudadas)} seriam alteradas, "
          f"{len(fora)} seriam removidas (não são vaga docente)")
    for antes, depois in mudadas[:8]:
        for campo in ("titulo", "area", "instituicao"):
            if antes[campo] != depois[campo]:
                print(f"  {campo}: {str(antes[campo])[:52]!r}\n      -> {str(depois[campo])[:52]!r}")
    for d in fora[:8]:
        print(f"  REMOVE: {str(d['titulo'])[:70]!r}")
    if not aplicar:
        print("\n(simulação — rode com --aplicar para gravar)")
        return
    for chave in chaves_fora:
        con.execute("DELETE FROM vagas WHERE chave=?", (chave,))
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
    print(f"gravado: {len(mudadas)} vagas corrigidas, {len(fora)} removidas, "
          f"{len(registros)} no banco; exportações refeitas")


if __name__ == "__main__":
    main("--aplicar" in sys.argv)

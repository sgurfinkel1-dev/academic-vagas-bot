"""Vagas.com.br — agregador com HTML renderizado no servidor.
Cobre particulares que não usam Gupy (fundações, centros universitários etc.)."""
import logging
import re
from bs4 import BeautifulSoup

from ..extractors.html_extractor import baixar
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
BUSCAS = ["professor", "docente", "professor-de-ensino-superior"]
SUPERIOR = re.compile(r"ensino superior|universit|faculdade|docente|gradua|p[óo]s-gradua", re.I)


def buscar(max_por_fonte: int = 100) -> list[Vaga]:
    vagas, vistos = [], set()
    for slug in BUSCAS:
        html = baixar(f"https://www.vagas.com.br/vagas-de-{slug}")
        if not html:
            continue
        for c in BeautifulSoup(html, "lxml").select("li.vaga"):
            a = c.select_one("a.link-detalhes-vaga")
            if not a or a["href"] in vistos:
                continue
            vistos.add(a["href"])
            titulo = a.get("title") or a.get_text(" ", strip=True)
            emp = c.select_one(".emprVaga")
            loc = c.select_one(".vaga-local")
            local = loc.get_text(" ", strip=True) if loc else ""
            texto = f"{titulo} {c.get_text(' ', strip=True)[:400]}"
            if not re.search(r"professor|docente|pesquisador|coordenador de curso|tutor", titulo, re.I):
                continue  # cargo precisa ser de docência
            if not SUPERIOR.search(texto):
                continue  # só ensino superior
            vagas.append(Vaga(
                titulo=titulo[:200],
                instituicao=emp.get_text(strip=True)[:80] if emp else "confidencial",
                classificacao_instituicao="privada",
                natureza="emprego CLT (docente privado)",
                cidade=local.split("/")[0].strip()[:60],
                estado=clf.extrair_estado(local),
                titulacao_exigida=clf.classificar_titulacao(texto),
                link_oficial="https://www.vagas.com.br" + a["href"],
                fonte=f"Vagas.com ({slug})",
                trecho_comprovacao=texto[:300],
                confianca="alto",
            ))
            if len(vagas) >= max_por_fonte:
                return vagas
    return vagas

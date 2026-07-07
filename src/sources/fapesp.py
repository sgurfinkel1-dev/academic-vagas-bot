"""FAPESP Oportunidades — bolsas e pós-doutorado."""
import logging
from bs4 import BeautifulSoup

from ..extractors.html_extractor import baixar
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://fapesp.br/oportunidades/"


def buscar(areas: list[str], max_por_fonte: int = 100) -> list[Vaga]:
    html = baixar(URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    vagas = []
    for a in soup.select("a[href*='/oportunidades/']"):
        titulo = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if len(titulo) < 15 or href.rstrip("/").endswith("oportunidades"):
            continue
        link = href if href.startswith("http") else "https://fapesp.br" + href
        texto = titulo.lower()
        area_match = next((ar for ar in areas if ar.lower() in texto), "")
        vagas.append(Vaga(
            titulo=titulo,
            instituicao="ver oportunidade (FAPESP)",
            classificacao_instituicao="agência/fundação",
            natureza=clf.classificar_natureza(titulo) or "bolsa",
            area=area_match,
            estado="SP",
            titulacao_exigida=clf.classificar_titulacao(titulo),
            link_oficial=link,
            fonte="FAPESP Oportunidades",
            trecho_comprovacao=titulo,
            confianca="alto",
        ))
        if len(vagas) >= max_por_fonte:
            break
    return vagas

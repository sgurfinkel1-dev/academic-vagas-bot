"""FAPESP Oportunidades — bolsas e pós-doutorado."""
import logging
import re
from bs4 import BeautifulSoup

from ..extractors.html_extractor import baixar
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://fapesp.br/oportunidades/"
# o anúncio vem num texto só: "Bolsa de X Instituição: Y Cidade: Z Inscrições até: ..."
ROTULO_SEGUINTE = re.compile(r"\s*(?:Cidade|Inscri[çc][õo]es|Publicad[ao]|Área|Programa)\s*:", re.I)


def partes(titulo: str) -> tuple[str, str]:
    """Separa o assunto da vaga do nome da instituição. Sem isso o nome da casa
    ("Escola de Filosofia, Letras...") era lido como a área da vaga."""
    assunto, _, resto = titulo.partition("Instituição:")
    casa = ROTULO_SEGUINTE.split(resto.strip(), maxsplit=1)[0].strip() if resto else ""
    return (assunto.strip(" -–") or titulo), casa


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
        assunto, casa = partes(titulo)
        texto = assunto.lower()
        area_match = next((ar for ar in areas if ar.lower() in texto), "") \
            or clf.classificar_area(assunto)
        vagas.append(Vaga(
            titulo=assunto[:200],
            instituicao=casa[:150] or "ver oportunidade (FAPESP)",
            classificacao_instituicao="agência/fundação",
            natureza=clf.classificar_natureza(assunto) or "bolsa",
            area=area_match,
            estado="SP",
            titulacao_exigida=clf.classificar_titulacao(assunto),
            link_oficial=link,
            fonte="FAPESP Oportunidades",
            trecho_comprovacao=titulo,
            confianca="alto",
        ))
        if len(vagas) >= max_por_fonte:
            break
    return vagas

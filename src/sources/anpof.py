"""ANPOF — agenda de concursos e seleções (anpof.org.br), o agregador de vagas de
filosofia do Brasil. A listagem vem no HTML estático, então não precisa de navegador.
"""
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..database.models import Vaga
from ..extractors import llm_classifier as clf
from ..extractors.html_extractor import baixar

log = logging.getLogger("bot")
URL = "https://anpof.org.br/agenda/concursos-e-selecoes"
DATA = re.compile(r"(\d{2}/\d{2}/\d{4})")
# "São Gabriel da Cachoeira (AM)" ou "Manaus-AM" — a UF fecha a linha do item
UF_FINAL = re.compile(r"[(\-\s]([A-Z]{2})\)?\s*$")


# sigla de universidade no título: UFG, UNICAMP, PUC-Rio, UFRGS...
SIGLA = re.compile(r"\b(U[FEN][A-Z]{1,5}|PUC(?:-[A-Za-z]+)?|UNI[A-Z]{2,7}|IF[A-Z]{1,4}|CEFET(?:-[A-Z]{2})?)\b")


def _instituicao(texto: str) -> str:
    m = SIGLA.search(texto)
    return m.group(1) if m else "ver anúncio"


def _item(div, base: str) -> Vaga | None:
    texto = div.get_text(" ", strip=True)
    # o item tem mais de uma âncora; a da vaga é a que aponta para um slug da categoria
    a = next((x for x in div.find_all("a", href=True)
              if re.search(r"concursos-e-selecoes/.+", x["href"])), None)
    if not a:
        return None
    titulo = a.get_text(" ", strip=True)
    if not titulo:
        return None
    m = DATA.search(texto)
    publicacao = m.group(1) if m else ""
    uf = UF_FINAL.search(texto)
    prazo = clf.extrair_prazo(texto)
    return Vaga(
        titulo=titulo[:200],
        instituicao=_instituicao(f"{titulo} {texto}"),
        classificacao_instituicao=clf.classificar_instituicao(titulo),
        natureza=clf.classificar_natureza(titulo),
        # o site é exclusivamente de filosofia; só refina se o título disser algo mais preciso
        area=clf.classificar_area(titulo) or "filosofia",
        estado=uf.group(1) if uf and uf.group(1) in ESTADOS else clf.extrair_estado(texto),
        titulacao_exigida=clf.classificar_titulacao(titulo),
        data_publicacao=publicacao,
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=urljoin(base, a["href"]),
        fonte="ANPOF (concursos e seleções)",
        trecho_comprovacao=texto[:300],
        confianca="alto",
    )


ESTADOS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
           "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}


def buscar(dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Itens publicados nos últimos `dias`. Sem data = mantém (listagem é do topo, atual)."""
    html = baixar(URL)
    if not html:
        log.warning("ANPOF: não consegui baixar a listagem")
        return []
    corte = date.today() - timedelta(days=dias)
    vagas = []
    for div in BeautifulSoup(html, "lxml").select("div.lista-agenda-item"):
        v = _item(div, URL)
        if not v:
            continue
        if v.data_publicacao:
            try:
                if datetime.strptime(v.data_publicacao, "%d/%m/%Y").date() < corte:
                    continue
            except ValueError:
                pass
        vagas.append(v)
        if len(vagas) >= max_por_fonte:
            break
    log.info("ANPOF: %d itens dentro do período", len(vagas))
    return vagas

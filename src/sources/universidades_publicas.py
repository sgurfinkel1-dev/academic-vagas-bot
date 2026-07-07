"""Varre páginas oficiais de concursos listadas em config.yaml (paginas_concursos)."""
import logging
import re
import warnings
from urllib.parse import urljoin
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from ..extractors.html_extractor import baixar
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
PADRAO_VAGA = re.compile(
    r"professor|docente|pesquisador|pós.doutor|magistério|processo seletivo|concurso", re.I)


def buscar(paginas: list[dict], max_por_fonte: int = 100) -> list[Vaga]:
    vagas = []
    for pag in paginas:
        html = baixar(pag["url"])
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        achados = 0
        for a in soup.find_all("a", href=True):
            titulo = a.get_text(" ", strip=True)
            if len(titulo) < 20 or not PADRAO_VAGA.search(titulo):
                continue
            link = urljoin(pag["url"], a["href"])
            texto = f"{pag['nome']} {titulo}"
            prazo = clf.extrair_prazo(titulo)
            vagas.append(Vaga(
                titulo=titulo[:200],
                instituicao=pag["nome"],
                classificacao_instituicao=clf.classificar_instituicao(texto),
                natureza=clf.classificar_natureza(titulo),
                titulacao_exigida=clf.classificar_titulacao(titulo),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial=link,
                link_edital_pdf=link if link.lower().endswith(".pdf") else "",
                fonte=f"Página oficial de concursos ({pag['nome']})",
                trecho_comprovacao=titulo[:300],
                confianca="alto",
            ))
            achados += 1
            if achados >= max_por_fonte:
                break
    return vagas

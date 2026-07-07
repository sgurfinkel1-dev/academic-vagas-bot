"""Busca aberta complementar via Bing (sem chave de API; DuckDuckGo exige challenge JS).
Resultados entram com confiança baixa — validar em fonte oficial.
"""
import logging
from urllib.parse import quote
from bs4 import BeautifulSoup

from ..extractors.html_extractor import baixar
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://www.bing.com/search"


def buscar(termos: list[str], areas: list[str], max_por_fonte: int = 50) -> list[Vaga]:
    vagas = []
    consultas = [f'"{t}" "{a}" inscrições site:.br' for t in termos[:4] for a in areas[:2]]
    for q in consultas:
        html = baixar(f"{URL}?q={quote(q)}&setlang=pt-BR")
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for res in soup.select("li.b_algo")[:10]:
            a = res.select_one("h2 a")
            snippet = res.select_one("p")
            if not a:
                continue
            titulo = a.get_text(" ", strip=True)
            trecho = snippet.get_text(" ", strip=True) if snippet else ""
            texto = f"{titulo} {trecho}"
            prazo = clf.extrair_prazo(texto)
            vagas.append(Vaga(
                titulo=titulo[:200],
                instituicao="verificar na página",
                classificacao_instituicao=clf.classificar_instituicao(texto),
                natureza=clf.classificar_natureza(texto),
                area=next((ar for ar in areas if ar.lower() in texto.lower()), ""),
                estado=clf.extrair_estado(texto),
                titulacao_exigida=clf.classificar_titulacao(texto),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial=a.get("href", ""),
                fonte=f"Busca aberta ({q[:60]})",
                trecho_comprovacao=trecho[:300],
                confianca="baixo",
                observacoes="Resultado de busca aberta — confirmar em fonte oficial.",
            ))
            if len(vagas) >= max_por_fonte:
                return vagas
    return vagas

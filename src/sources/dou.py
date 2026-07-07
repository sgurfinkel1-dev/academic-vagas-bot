"""Diário Oficial da União via busca do in.gov.br (endpoint JSON da consulta pública).
ponytail: para volume/robustez use INLABS (exige cadastro) ou Ro-DOU.
"""
import logging
import time
from datetime import date, timedelta

import httpx

from ..extractors.html_extractor import HEADERS
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://www.in.gov.br/consulta/-/buscar/dou"


def _consultar(client: httpx.Client, params: dict, tentativas: int = 3):
    for i in range(tentativas):
        try:
            r = client.get(URL, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("DOU tentativa %d falhou: %s", i + 1, e)
            time.sleep(5 * (i + 1))
    return None


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas = []
    desde = (date.today() - timedelta(days=dias)).strftime("%d-%m-%Y")
    ate = date.today().strftime("%d-%m-%Y")
    headers = HEADERS | {"Accept": "application/json", "Referer": "https://www.in.gov.br/consulta/"}
    client = httpx.Client(headers=headers, timeout=90, follow_redirects=True)
    try:
        client.get("https://www.in.gov.br/consulta/")  # cookies de sessão
    except Exception as e:
        log.warning("DOU: falha ao abrir sessão: %s", e)
    for i, termo in enumerate(termos):
        params = {
            "q": f'"{termo}"', "s": "do3", "exactDate": "personalizado",
            "publishFrom": desde, "publishTo": ate, "sortType": "0", "delta": "20",
        }
        dados = _consultar(client, params)
        itens = (dados or {}).get("jsonArray", [])
        if dados is None:
            log.warning("DOU indisponível para termo %r", termo)
            if i == 0:  # fonte fora do ar — não insistir nos outros termos
                log.warning("DOU aparenta estar fora do ar; pulando os demais termos")
                break
        for item in itens[:max_por_fonte]:
            titulo = item.get("title", "")
            texto = f"{titulo} {item.get('content', '')} {item.get('hierarchyStr', '')}"
            prazo = clf.extrair_prazo(texto)
            vagas.append(Vaga(
                titulo=titulo or termo,
                instituicao=item.get("hierarchyStr", "").split("/")[-1].strip() or "ver edital",
                classificacao_instituicao=clf.classificar_instituicao(texto),
                natureza=clf.classificar_natureza(texto),
                area="",
                estado=clf.extrair_estado(texto),
                titulacao_exigida=clf.classificar_titulacao(texto),
                data_publicacao=item.get("pubDate", ""),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial="https://www.in.gov.br/web/dou/-/" + item.get("urlTitle", ""),
                fonte=f"DOU (busca: {termo})",
                trecho_comprovacao=(item.get("content", "") or titulo)[:300],
                confianca="alto",
            ))
    client.close()
    return vagas

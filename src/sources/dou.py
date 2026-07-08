"""DOU via página de consulta do in.gov.br renderizada com Scrapling + Chrome real.
Os resultados vêm embutidos num <script> com jsonArray (mesma fonte que o Ro-DOU usa).
"""
import json
import logging
from datetime import date, timedelta
from urllib.parse import quote

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
BUSCA = ("https://www.in.gov.br/consulta/-/buscar/dou?q=%22{termo}%22&s=do3&sortType=0"
         "&delta={delta}&exactDate=personalizado&publishFrom={desde}&publishTo={ate}")


def _itens(termo: str, desde: str, ate: str, delta: int):
    from scrapling.fetchers import DynamicFetcher
    url = BUSCA.format(termo=quote(termo), delta=min(delta, 75), desde=desde, ate=ate)
    p = DynamicFetcher.fetch(url, real_chrome=True, headless=True, timeout=120000, wait=8000)
    html = p.html_content
    i = html.find("jsonArray")
    if i < 0:
        return []
    ini = html.find("{", html.rfind("<script", 0, i))
    fim = html.find("</script>", i)
    corpo = html[ini:fim]
    dados = json.loads(corpo[:corpo.rfind("}") + 1])
    return dados.get("jsonArray", [])


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas = []
    desde = (date.today() - timedelta(days=dias)).strftime("%d-%m-%Y")
    ate = date.today().strftime("%d-%m-%Y")
    for i, termo in enumerate(termos):
        try:
            itens = _itens(termo, desde, ate, max_por_fonte)
        except Exception as e:
            log.warning("DOU falhou para %r: %s", termo, str(e)[:150])
            if i == 0:  # ponytail: fonte fora do ar — não insistir nos outros termos
                log.warning("DOU aparenta estar fora do ar; pulando os demais termos")
                break
            continue
        log.info("DOU %r: %d itens", termo, len(itens))
        for item in itens[:max_por_fonte]:
            titulo = item.get("title", "")
            texto = f"{titulo} {item.get('content', '')} {item.get('hierarchyStr', '')}"
            prazo = clf.extrair_prazo(texto)
            vagas.append(Vaga(
                titulo=titulo or termo,
                instituicao=(item.get("hierarchyStr") or "").split("/")[-1].strip() or "ver edital",
                classificacao_instituicao=clf.classificar_instituicao(texto),
                natureza=clf.classificar_natureza(texto),
                estado=clf.extrair_estado(texto),
                titulacao_exigida=clf.classificar_titulacao(texto),
                data_publicacao=item.get("pubDate", ""),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial="https://www.in.gov.br/web/dou/-/" + (item.get("urlTitle") or ""),
                fonte=f"DOU (busca: {termo})",
                trecho_comprovacao=(item.get("content", "") or titulo)[:300],
                confianca="alto",
            ))
    return vagas

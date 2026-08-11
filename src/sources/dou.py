"""DOU via página de consulta do in.gov.br renderizada com Scrapling + Chrome real.
Os resultados vêm embutidos num <script> com jsonArray (mesma fonte que o Ro-DOU usa).
"""
import json
import logging
import os
import re
from datetime import date, timedelta
from urllib.parse import quote

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
# Busca SEM restrição de seção (cobre Seções 1, 2 e 3)
# sortType=1 ordena por data (mais recente primeiro), não por relevância
BUSCA = ("https://www.in.gov.br/consulta/-/buscar/dou?q=%22{termo}%22&sortType=1"
         "&delta={delta}&exactDate=personalizado&publishFrom={desde}&publishTo={ate}&p={pagina}")
# Windows local: Chromium empacotado não abre (side-by-side), usa Chrome instalado.
# Linux/CI: sem Chrome instalado, usa o Chromium empacotado (AVB_REAL_CHROME=0).
REAL_CHROME = os.getenv("AVB_REAL_CHROME", "1") != "0"
# Limite máximo de páginas a paginar (proteção contra loops infinitos)
MAX_PAGINAS = 10


def _itens(termo: str, desde: str, ate: str, delta: int):
    """Busca no DOU paginando até esgotar resultados ou bater limite de páginas."""
    from scrapling.fetchers import DynamicFetcher

    todos_itens = []
    pagina = 0
    delta_por_page = min(delta, 75)  # DOU limita a 75 itens por página

    while True:
        url = BUSCA.format(
            termo=quote(termo),
            delta=delta_por_page,
            desde=desde,
            ate=ate,
            pagina=pagina
        )

        try:
            p = DynamicFetcher.fetch(url, real_chrome=REAL_CHROME, headless=True, timeout=120000, wait=8000)
            html = p.html_content
            i = html.find("jsonArray")
            if i < 0:
                break

            ini = html.find("{", html.rfind("<script", 0, i))
            fim = html.find("</script>", i)
            corpo = html[ini:fim]
            dados = json.loads(corpo[:corpo.rfind("}") + 1])
            itens_desta_pagina = dados.get("jsonArray", [])

            if not itens_desta_pagina:
                # Nenhum resultado nesta página = fim da paginação
                break

            todos_itens.extend(itens_desta_pagina)
            pagina += 1

            # Proteção: limitar paginação
            if pagina >= MAX_PAGINAS:
                log.warning("DOU %r: atingiu limite de %d páginas", termo, MAX_PAGINAS)
                break

            # Se conseguimos menos itens que o esperado, é sinal de fim
            if len(itens_desta_pagina) < delta_por_page:
                break

        except Exception as e:
            log.warning("DOU %r (página %d): erro na paginação: %s", termo, pagina, str(e)[:150])
            # Continua com o que conseguiu até agora
            break

    log.info("DOU %r: %d páginas, %d itens total", termo, pagina, len(todos_itens))
    return todos_itens


# o DOU devolve o trecho com a busca destacada: <span class='highlight' ...>termo</span>
TAG = re.compile(r"<[^>]+>")


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", texto or "")).strip()


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
            titulo = _limpo(item.get("title", ""))
            conteudo = _limpo(item.get("content", ""))
            texto = f"{titulo} {conteudo} {item.get('hierarchyStr', '')}"
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
                trecho_comprovacao=(conteudo or titulo)[:600],
                confianca="alto",
            ))
    return vagas


# "concurso público" saiu da lista: sozinho não indica vaga docente (técnico-administrativo
# também é concurso público). O cargo tem de aparecer no texto.
ANCORA_VAGA = re.compile(
    r"professor|docente|pesquisador|pós.doutor|magistério superior|"
    r"processo seletivo simplificado|bolsa de|monitor|substituto|visitante", re.I)


def buscar_palavra(palavra: str, dias: int = 30, max_por_fonte: int = 75) -> list[Vaga]:
    """Busca ao vivo no DOU pela área (frase única) e filtra por termos de vaga
    localmente — o 'E' entre duas aspas quebra no motor do DOU, então filtramos aqui."""
    vagas = buscar([palavra], dias, max_por_fonte)
    academicas = [v for v in vagas
                  if ANCORA_VAGA.search(f"{v.titulo} {v.trecho_comprovacao}")
                  and _e_da_area(v, palavra)]
    for v in academicas:
        v.area = clf.classificar_area(v.titulo, v.trecho_comprovacao) or palavra
        v.fonte = f"DOU (área: {palavra})"
    return academicas


def _e_da_area(v: Vaga, palavra: str) -> bool:
    """O motor do DOU casa a palavra em qualquer ponto do ato — "continuidade lógica"
    num edital de previdência virava vaga de lógica. Só vale no título ou onde o
    edital declara a área da vaga."""
    alvo = re.compile(rf"\b{re.escape(palavra)}", re.I)
    if alvo.search(v.titulo):
        return True
    return any(alvo.search(m.group(1))
               for m in clf.CONTEXTO_AREA.finditer(v.trecho_comprovacao or ""))

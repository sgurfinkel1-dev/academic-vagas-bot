"""DOU via página de consulta do in.gov.br renderizada com Scrapling + Chrome real.
Os resultados vêm embutidos num <script> com jsonArray (mesma fonte que o Ro-DOU usa).
"""
import json
import logging
import os
import re
import time
from datetime import date, timedelta
from urllib.parse import quote

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

# sortType=1: ordenação por data (mais recentes primeiro)
# s: seção (do1, do2, do3, all)
URL_BASE = "https://www.in.gov.br/consulta/-/buscar/dou"
BUSCA = (URL_BASE + "?q=%22{termo}%22&s={secao}&sortType=1"
         "&delta={delta}&start={inicio}&exactDate=personalizado&publishFrom={desde}&publishTo={ate}")

REAL_CHROME = os.getenv("AVB_REAL_CHROME", "1") != "0"
# Esta página do DOU não pagina por URL. Testado no navegador em 11/08/2026:
# `p=0` e `p=1` devolvem a mesma lista, e `start=0` e `start=20` também — o
# site ignora os dois parâmetros. Com teto 10, cada termo baixaria a MESMA
# página dez vezes por seção: 19 termos x 3 seções x 10 = 570 carregamentos de
# navegador, 8s de espera cada, horas de execução diária, e o dedup jogando
# tudo fora no fim. Zero cobertura a mais.
#
# Fica 1 até existir paginação verificada. Para ampliar o DOU de verdade o
# caminho é o INLABS (src/sources/inlabs.py, escrito e nunca ligado): dados
# oficiais em XML, sem raspagem e sem parâmetro a adivinhar. O laço pelas três
# seções, esse sim, foi verificado e continua valendo.
MAX_PAGINAS = 1


def _itens_pagina(termo: str, secao: str, desde: str, ate: str, delta: int, inicio: int):
    from scrapling.fetchers import DynamicFetcher
    url = BUSCA.format(termo=quote(termo), secao=secao, delta=delta, inicio=inicio, desde=desde, ate=ate)
    log.debug("DOU fetch: %s", url)
    
    # wait=8000 é necessário porque a página do DOU demora a renderizar o script de resultados
    p = DynamicFetcher.fetch(url, real_chrome=REAL_CHROME, headless=True, timeout=120000, wait=8000)
    html = p.html_content
    return _parse_html_dou(html)


def _parse_html_dou(html: str) -> list[dict]:
    """Extrai o jsonArray embutido no HTML da página de busca do DOU."""
    if not html:
        return []
    i = html.find("jsonArray")
    if i < 0:
        return []
    try:
        # Localiza o início do objeto JSON que contém o jsonArray
        ini = html.find("{", html.rfind("<script", 0, i))
        fim = html.find("</script>", i)
        corpo = html[ini:fim]
        # Limpa o corpo para o json.loads (pega até o último fechamento de chaves válido)
        json_str = corpo[:corpo.rfind("}") + 1]
        dados = json.loads(json_str)
        return dados.get("jsonArray", [])
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Falha ao parsear JSON do DOU: %s", e)
        # O teste de fixture deve falhar aqui se o formato mudar
        raise


def _itens_com_paginacao(termo: str, desde: str, ate: str, max_itens: int):
    """Varre as seções e faz paginação, deduplicando resultados."""
    todas_vagas = {}  # (urlTitle, pubDate) -> item
    # Seções do DOU: 1 (Atos Normativos), 2 (Atos de Pessoal), 3 (Contratos/Editais)
    # Concursos de professor podem sair em qualquer uma (abertura na 3, pessoal na 2, etc)
    secoes = ["do1", "do2", "do3"]
    
    delta = 50  # itens por página (site aceita até 100, mas 50 é mais estável)
    
    for secao in secoes:
        paginas_secao = 0
        for p in range(MAX_PAGINAS):
            inicio = p * delta
            try:
                itens = _itens_pagina(termo, secao, desde, ate, delta, inicio)
                if not itens:
                    break
                
                novos = 0
                for item in itens:
                    # Chave de unicidade: urlTitle (identificador do ato) + data
                    chave = (item.get("urlTitle"), item.get("pubDate"))
                    if chave not in todas_vagas:
                        todas_vagas[chave] = item
                        novos += 1
                
                paginas_secao += 1
                # Se não veio uma página cheia, ou não trouxe nada novo, paramos a seção
                if len(itens) < delta or novos == 0:
                    break
                    
                if len(todas_vagas) >= max_itens:
                    break
            except Exception as e:
                log.warning("Erro na seção %s, página %d do DOU: %s", secao, p, e)
                break
        
        if paginas_secao > 0:
            log.debug("DOU %s: %d páginas processadas", secao, paginas_secao)

    return list(todas_vagas.values())


# o DOU devolve o trecho com a busca destacada: <span class='highlight' ...>termo</span>
TAG = re.compile(r"<[^>]+>")


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", texto or "")).strip()


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 200) -> list[Vaga]:
    vagas = []
    desde = (date.today() - timedelta(days=dias)).strftime("%d-%m-%Y")
    ate = date.today().strftime("%d-%m-%Y")
    
    for i, termo in enumerate(termos):
        start_time = time.time()
        try:
            # max_por_fonte aumentado para 200 para acomodar múltiplas seções/páginas
            itens = _itens_com_paginacao(termo, desde, ate, max_por_fonte)
        except Exception as e:
            log.warning("DOU falhou criticamente para %r: %s", termo, str(e)[:150])
            if i == 0:
                log.warning("DOU aparenta estar fora do ar; pulando os demais termos")
                break
            continue
            
        duration = time.time() - start_time
        log.info("DOU %r: %d itens encontrados em %.1fs", termo, len(itens), duration)
        
        for item in itens[:max_por_fonte]:
            titulo = _limpo(item.get("title", ""))
            conteudo = _limpo(item.get("content", ""))
            # O campo hierarchyStr contém a hierarquia do órgão (ex: Ministério da Educação/UFOP)
            hierarquia = item.get("hierarchyStr") or ""
            texto = f"{titulo} {conteudo} {hierarquia}"
            
            prazo = clf.extrair_prazo(texto)
            vagas.append(Vaga(
                titulo=titulo or termo,
                instituicao=hierarquia.split("/")[-1].strip() or "ver edital",
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


# "concurso público" sozinho não indica vaga docente. O cargo tem de aparecer no texto.
ANCORA_VAGA = re.compile(
    r"professor|docente|pesquisador|pós.doutor|magistério superior|"
    r"processo seletivo simplificado|bolsa de|monitor|substituto|visitante", re.I)


def buscar_palavra(palavra: str, dias: int = 30, max_por_fonte: int = 150) -> list[Vaga]:
    """Busca ao vivo no DOU pela área (frase única) e filtra por termos de vaga localmente."""
    vagas = buscar([palavra], dias, max_por_fonte)
    academicas = [v for v in vagas
                  if ANCORA_VAGA.search(f"{v.titulo} {v.trecho_comprovacao}")
                  and _e_da_area(v, palavra)]
    for v in academicas:
        v.area = clf.classificar_area(v.titulo, v.trecho_comprovacao) or palavra
        v.fonte = f"DOU (área: {palavra})"
    return academicas


def _e_da_area(v: Vaga, palavra: str) -> bool:
    """Valida se a palavra-chave aparece no título ou no contexto de área do edital."""
    alvo = re.compile(rf"\b{re.escape(palavra)}", re.I)
    if alvo.search(v.titulo):
        return True
    return any(alvo.search(m.group(1))
               for m in clf.CONTEXTO_AREA.finditer(v.trecho_comprovacao or ""))

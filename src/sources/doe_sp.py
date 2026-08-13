"""Diário Oficial do Estado de São Paulo (doe.sp.gov.br).

Por que existe: USP, Unicamp e UNESP são estaduais e publicam edital de docente
aqui, não no DOU. O Querido Diário só cobre diário municipal, então essas vagas
não entravam por fonte nenhuma — medido em 12/08/2026, uma busca por
"epidemiologia" no robô não achava o EDITAL DVACAD/FM/141/2026 (Professor
Doutor, Depto. de Medicina Preventiva da FMUSP) que o Google mostrava.

O portal é um SPA em Next.js, mas por trás dele há uma API JSON aberta, sem
chave nem cookie. O contrato foi capturado do próprio site em 13/08/2026:

    GET /v2/advanced-search/publications
        ?Terms[0]=<termo>&FromDate=AAAA-M-D&ToDate=AAAA-M-D
        &periodStartingDate=AAAA-M-D&PageNumber=1&PageSize=20&SortField=Date

Duas armadilhas medidas: a data vai SEM zero à esquerda (2026-8-13, não
2026-08-13) e o termo é array indexado (Terms[0]). Errar qualquer um dos dois
devolve 200 com totalItems=0 — falha silenciosa, não erro.

Rendimento em 30 dias (13/08/2026): concurso 1.425, professor doutor 410,
epidemiologia 27. Com a lista inteira de termos do config (41), 411 vagas em
41 s, cobrindo 62 unidades — Unicamp, 11 campi da UNESP e várias da USP.

# ponytail: prazo_inscricao sai vazio, porque o `excerpt` da busca vem truncado
# antes da data. O texto completo existe e é acessível — GET /v2/publications/
# {id} devolve o campo `content` com o edital inteiro (medido: 1,7 KB a 394 KB).
# Não foi ligado porque custa uma requisição por vaga (seriam 411) e porque
# clf.extrair_prazo não casou com nenhum dos 10 editais testados: o DOE-SP
# redige o prazo de forma diferente do DOU. Para fechar isto: ensinar o
# extrator a redação daqui primeiro, medir o acerto, e só então pagar a
# requisição extra.
"""
import logging
import re
from datetime import date, timedelta

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

API = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
SITE = "https://doe.sp.gov.br"
# a API recusa requisição sem Origin/Referer do próprio portal
CABECALHO = {"User-Agent": "academic-vagas-bot", "Accept": "application/json",
             "Origin": SITE, "Referer": SITE + "/"}

# O termo pesquisado não basta como filtro: "Direito" e "Economia" casam com
# qualquer ato administrativo. Exigir cargo é o mesmo critério já usado no
# inlabs.py, e pela mesma razão — sem ele a Seção Empresarial entra inteira.
CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)
# Portaria de nomeação cita o concurso que nomeou, então o corpo não distingue:
# é preciso barrar pelo verbo do ato.
FORA = re.compile(r"nomea[çc][ãa]o|exonera[çc][ãa]o|demiss[ãa]o|aposentadoria|"
                  r"licita[çc][ãa]o|preg[ãa]o", re.I)
# No DOE-SP o tipo do ato só existe no título — não há campo equivalente ao
# artType do INLABS. Medido em 13/08/2026 sobre 108 publicações: exigir cargo no
# corpo deixava passar 78, das quais 45 eram portaria/despacho/apostila que
# apenas citam um professor. Exigir o ato no título derruba para 33 sem perder
# nenhum edital de abertura.
ATO_NO_TITULO = re.compile(r"edital|concurso|processo seletivo|sele[çc][ãa]o|"
                           r"abertura de inscri", re.I)


def _data_api(dt: date) -> str:
    """AAAA-M-D sem zero à esquerda — é o formato que o portal emite."""
    return f"{dt.year}-{dt.month}-{dt.day}"


def _instituicao(hierarquia: str) -> str:
    """'Executivo > Atos ... > Universidade de São Paulo > ... > Faculdade de
    Medicina' -> 'Universidade de São Paulo — Faculdade de Medicina'."""
    partes = [p.strip() for p in (hierarquia or "").split(">") if p.strip()]
    orgao = next((p for p in partes if re.search(r"universidade|instituto|"
                                                 r"funda[çc][ãa]o|secretaria|"
                                                 r"faculdade|centro", p, re.I)), "")
    unidade = partes[-1] if partes and partes[-1] != orgao else ""
    if orgao and unidade:
        return f"{orgao} — {unidade}"
    return orgao or unidade or "Governo do Estado de São Paulo"


def _vaga(item: dict, termo: str) -> Vaga | None:
    titulo = (item.get("title") or "").strip()
    trecho = (item.get("excerpt") or "").strip()
    hierarquia = item.get("hierarchy") or ""
    tudo = f"{titulo} {trecho} {hierarquia}"
    if not CARGO.search(tudo) or FORA.search(tudo):
        return None
    if not ATO_NO_TITULO.search(titulo):
        return None
    slug = item.get("slug") or ""
    prazo = clf.extrair_prazo(tudo)
    return Vaga(
        titulo=titulo[:200],
        instituicao=_instituicao(hierarquia),
        classificacao_instituicao=clf.classificar_instituicao(tudo),
        natureza=clf.classificar_natureza(tudo),
        estado="SP",
        titulacao_exigida=clf.classificar_titulacao(tudo),
        data_publicacao=(item.get("date") or "")[:10],
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=f"{SITE}/{slug}" if slug else SITE,
        fonte=f"DOE-SP (busca: {termo})",
        trecho_comprovacao=trecho[:600] or titulo,
        confianca="alto",
    )


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas: list[Vaga] = []
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    with httpx.Client(timeout=30, headers=CABECALHO) as cli:
        for termo in termos:
            pagina = 1
            while len(vagas) < max_por_fonte:
                params = {"Terms[0]": termo,
                          "FromDate": _data_api(inicio), "ToDate": _data_api(hoje),
                          "periodStartingDate": _data_api(inicio),
                          "PageNumber": pagina, "PageSize": 20, "SortField": "Date"}
                try:
                    r = cli.get(API, params=params)
                except httpx.HTTPError as e:
                    log.warning("DOE-SP '%s' p%d: %s", termo, pagina, e)
                    break
                if r.status_code != 200:
                    log.warning("DOE-SP '%s': HTTP %d", termo, r.status_code)
                    break
                dados = r.json()
                itens = dados.get("items") or []
                if not itens:
                    break
                for it in itens:
                    v = _vaga(it, termo)
                    if v:
                        vagas.append(v)
                    if len(vagas) >= max_por_fonte:
                        break
                # ponytail: teto de 5 páginas (100 publicações) por termo. Com ~38
                # termos no config, ler tudo de "concurso" (72 páginas) faria a
                # coleta demorar mais que o resto do robô junto. Suba se faltar vaga.
                if pagina >= min(5, dados.get("totalPages") or 1):
                    break
                pagina += 1
    log.info("DOE-SP: %d vagas", len(vagas))
    return vagas

"""Diário Oficial do Estado do Paraná (dioe.pr.gov.br).

Por que existe: o Paraná tem sete universidades estaduais (UEL, UEM, UEPG,
UNIOESTE, UNICENTRO, UENP, UNESPAR) e o edital de docente delas sai no diário
estadual, não no DOU. O Querido Diário só cobre diário municipal, então até
aqui essas vagas não entravam por fonte nenhuma.

O portal é um SPA em AngularJS, mas por trás dele há um Elasticsearch aberto,
sem chave nem cookie. O contrato foi lido do bundle /buscanova/assets/
javascripts/application.b15ebb8e.js e verificado em 13/08/2026:

    GET /busca/busca/buscar/query/{pagina}/di:AAAA-MM-DD/df:AAAA-MM-DD/?1=1&q={termo}

Três detalhes que só aparecem testando:

1. A página é ÍNDICE ZERO — `query/0` é a primeira. `query/1` já é a segunda,
   com 10 resultados diferentes. Começar em 1 pula silenciosamente 10 itens.
2. As datas vão em segmento de CAMINHO (`di:`/`df:`), não em query string, e
   COM zero à esquerda (2026-08-13). É o oposto do DOE-SP, que exige sem zero.
3. O `q` aceita frase entre aspas duplas e o índice é dobrado por acento:
   medido em 13/08/2026 sobre 365 dias, "magistério superior" e "magisterio
   superior" devolvem os mesmos 145 resultados. Frase de fato filtra
   ("concurso publico" 49 contra `concurso` 62 em 30 dias), então um zero aqui
   é zero de verdade, não erro de formato.

A diferença estrutural em relação ao DOE-SP: aqui a unidade indexada é a
PÁGINA do PDF, não a publicação. Não existe campo de título, e `conteudo` é o
texto da página inteira — dez atos distintos de órgãos distintos, com as duas
colunas do PDF intercaladas pelo OCR. Por isso o filtro trabalha por
proximidade dentro da página (ver JANELA) em vez de olhar um título.

Rendimento medido em 13/08/2026: `professor` devolve 186 páginas em 30 dias,
2.993 em 365; "de abertura de concurso" devolve 22 em 365 dias.
"""
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

SITE = "https://dioe.pr.gov.br"
API = SITE + "/busca/busca/buscar/query"
CABECALHO = {"User-Agent": "academic-vagas-bot", "Accept": "application/json",
             "Referer": SITE + "/buscanova/"}

CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)

# O ato que ABRE vaga. No DOE-SP bastava exigir essas palavras no título; aqui
# não há título, então elas precisam vir com o complemento que distingue
# abertura de mera citação — "concurso público" sozinho aparece em toda portaria
# de contratação que cita o certame que aprovou o candidato.
ATO = re.compile(
    r"(?:edital|aviso)[^.]{0,90}?de abertura|"
    r"abertura (?:de|das|do|dos)\s+(?:inscri|concurso|processo|edital|vagas)|"
    r"torna p[úu]blic\w{0,2}[^.]{0,70}?abertura|"
    r"inscri[çc][õo]es[^.]{0,50}?(?:estar[ãa]o|encontram.se|ficam)\s+abertas|"
    # Este último ramo é o mais fraco — "concurso público para provimento de
    # cargos" abre tanto vaga de docente quanto de agente universitário. Por
    # isso aqui o cargo é exigido DENTRO do próprio casamento, não só na janela:
    # sem isso o concurso de Agente Universitário da UNICENTRO (16751_40,
    # 22/04/2026) entrava só porque a página citava "docente" 600 caracteres
    # adiante.
    r"(?:concurso p[úu]blico|processo seletivo(?: simplificado)?|teste seletivo)"
    r"[^.]{0,110}?(?:para|destinad\w{1,2})[^.]{0,70}?"
    r"(?:professor|docente|magist[ée]rio|pesquisador)", re.I)

# Verbos de ato que NÃO abrem vaga. "contratar" no infinitivo é o verbo da
# portaria que contrata o aprovado; "contratação" (substantivo) é o que o
# próprio edital de PSS diz que vai fazer, e esse fica.
FORA = re.compile(
    r"nomea[çr]|exonera|demiss|aposentad|provento|insalubridade|licen[çc]a\b|"
    r"remo[çc][ãa]o|homologa|resultado (?:final|preliminar|parcial)|sorteio|"
    r"classifica[çc][ãa]o final|convoca[çt]|\bcontratar\b|licita[çt]|preg[ãa]o|"
    r"dispensa de|apostila|rescis|retifica|torna sem efeito|prorroga|"
    # "abertura das inscrições" também abre eleição de CIPA e de colegiado —
    # medido em 16753_40 (UNIOESTE, 24/04/2026), que entrava como se fosse vaga.
    r"elei[çc][ãa]o|\bCIPA\b|comiss[ãa]o interna|"
    # concurso de servidor não-docente usa exatamente a mesma fórmula de abertura
    r"agente universit[áa]rio|t[ée]cnico.administrativ", re.I)

# A SEED (educação básica) é o maior publicador de "professor" do DOE-PR e o app
# só quer ensino superior. Sem esta barreira o PSS de professor de colégio
# estadual entra como se fosse vaga de universidade.
BASICA = re.compile(
    r"escolas? do futuro|professor(?:es)? pedagogos?|educa[çc][ãa]o b[áa]sica|"
    r"ensino fundamental|ensino m[ée]dio|quadro pr[óo]prio do magist[ée]rio|"
    r"\bQPM\b|\bSEED\b|col[ée]gio estadual|rede estadual de ensino", re.I)

# Quanto o ato "enxerga" ao redor de si dentro da página. 700 caracteres é ~1
# ato inteiro no layout de duas colunas do DOE-PR; com 2.000 a janela alcança o
# ato vizinho e o ruído de uma portaria de nomeação contamina o edital ao lado.
JANELA = 700

# As sete estaduais do PR e os institutos estaduais de pesquisa. A sigla sozinha
# basta: o diário quase sempre escreve "UNIVERSIDADE ESTADUAL DE MARINGÁ" e
# "UEM" na mesma página.
INSTITUICOES = [
    (r"universidade estadual de londrina|\bUEL\b", "Universidade Estadual de Londrina (UEL)"),
    (r"universidade estadual de maring[áa]|\bUEM\b", "Universidade Estadual de Maringá (UEM)"),
    (r"universidade estadual de ponta grossa|\bUEPG\b", "Universidade Estadual de Ponta Grossa (UEPG)"),
    (r"universidade estadual do oeste do paran[áa]|\bUNIOESTE\b", "Universidade Estadual do Oeste do Paraná (UNIOESTE)"),
    (r"universidade estadual do centro.oeste|\bUNICENTRO\b", "Universidade Estadual do Centro-Oeste (UNICENTRO)"),
    (r"universidade estadual do norte do paran[áa]|\bUENP\b", "Universidade Estadual do Norte do Paraná (UENP)"),
    (r"universidade estadual do paran[áa]|\bUNESPAR\b", "Universidade Estadual do Paraná (UNESPAR)"),
    (r"funda[çc][ãa]o arauc[áa]ria", "Fundação Araucária"),
    (r"\bTECPAR\b|instituto de tecnologia do paran[áa]", "TECPAR"),
    (r"\bIDR.Paran[áa]\b|\bIAPAR\b", "IDR-Paraná"),
]
INSTITUICOES = [(re.compile(p, re.I), n) for p, n in INSTITUICOES]
FALLBACK = "Governo do Estado do Paraná"

# Onde começa a "manchete" do ato, para montar um título que não existe no dado.
CABECA = re.compile(r"edital|portaria|resolu[çc][ãa]o|aviso|comunicado|extrato", re.I)


def _url(termo: str, pagina: int, inicio: date, fim: date) -> str:
    """Página é ÍNDICE ZERO e as datas são segmento de caminho, com zero à esquerda."""
    return (f"{API}/{pagina}/di:{inicio.isoformat()}/df:{fim.isoformat()}/"
            f"?1=1&q={quote(termo, safe='')}")


def _instituicao(texto: str) -> str:
    for padrao, nome in INSTITUICOES:
        if padrao.search(texto):
            return nome
    return FALLBACK


def _titulo(conteudo: str, ini: int, fim: int) -> str:
    """Monta um título a partir do ato — o índice do DOE-PR não tem esse campo.

    Recua até o cabeçalho do ato ("Edital nº 001/2026-PRH, de abertura de...")
    porque começar no gatilho sozinho produz título sem o número do edital, e
    é o número que o usuário usa para achar a peça no site da universidade.
    """
    tras = conteudo[max(0, ini - 140):ini]
    m = list(CABECA.finditer(tras))
    comeco = max(0, ini - 140) + m[-1].start() if m else ini
    bruto = conteudo[comeco:fim + 160]
    bruto = re.split(r"(?<=[a-zà-ú0-9])\.\s", bruto)[0]  # corta na 1ª frase inteira
    return re.sub(r"\s+", " ", bruto).strip(" .,;-")[:200]


def _vagas_da_pagina(src: dict, termo: str) -> list[Vaga]:
    """Uma página do diário pode conter zero, um ou vários editais de abertura."""
    conteudo = src.get("conteudo") or ""
    data = (src.get("data") or "")[:10]
    diario, pagina = src.get("diario_id"), src.get("pagina")
    vagas, vistos = [], set()
    for m in ATO.finditer(conteudo):
        ini, fim = max(0, m.start() - JANELA), min(len(conteudo), m.end() + JANELA)
        janela = conteudo[ini:fim]
        if not CARGO.search(janela):
            continue
        if FORA.search(janela) or BASICA.search(janela):
            continue
        titulo = _titulo(conteudo, m.start(), m.end())
        # Dois gatilhos vizinhos no mesmo ato geram títulos que só diferem no
        # fim ("...Portaria nº 338/2026-PRH" e "...Portaria nº 338/2026-PRH
        # RESOL"). Deduplicar pelo título inteiro deixava os dois passarem.
        chave = titulo.lower()[:80]
        if chave in vistos:
            continue
        vistos.add(chave)
        prazo = clf.extrair_prazo(janela)
        instituicao = _instituicao(janela)
        if instituicao == FALLBACK:
            instituicao = _instituicao(conteudo)
        vagas.append(Vaga(
            titulo=titulo,
            instituicao=instituicao,
            # Classifica pelo NOME que já foi resolvido, não pelo texto da
            # página: a página inteira contém siglas de outros órgãos e o
            # classificador devolvia "pública federal" para a UEM por causa
            # delas.
            classificacao_instituicao=clf.classificar_instituicao(instituicao),
            natureza=clf.classificar_natureza(janela),
            estado="PR",
            titulacao_exigida=clf.classificar_titulacao(janela),
            data_publicacao=data,
            prazo_inscricao=prazo,
            status=clf.status_por_prazo(prazo),
            link_oficial=f"{SITE}/ver/{diario}/{pagina}/{quote(termo, safe='')}",
            link_edital_pdf=f"{SITE}/portal/edicoes/download/{diario}/{pagina}",
            fonte=f"DOE-PR (busca: {termo})",
            trecho_comprovacao=re.sub(r"\s+", " ", janela).strip()[:600],
            confianca="médio",  # a peça é uma PÁGINA inteira; o recorte é heurístico
        ))
    return vagas


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas: list[Vaga] = []
    chaves: set[str] = set()
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    with httpx.Client(timeout=60, headers=CABECALHO) as cli:
        for termo in termos:
            pagina = 0
            while len(vagas) < max_por_fonte:
                try:
                    r = cli.get(_url(termo, pagina, inicio, hoje))
                except httpx.HTTPError as e:
                    log.warning("DOE-PR '%s' p%d: %s", termo, pagina, e)
                    break
                if r.status_code != 200:
                    log.warning("DOE-PR '%s': HTTP %d", termo, r.status_code)
                    break
                try:
                    hits = (r.json().get("hits") or {}).get("hits") or []
                except ValueError as e:
                    log.warning("DOE-PR '%s': resposta não-JSON (%s)", termo, e)
                    break
                if not hits:
                    break
                for h in hits:
                    for v in _vagas_da_pagina(h.get("_source") or {}, termo):
                        # o mesmo edital costuma reaparecer em várias páginas e em
                        # vários termos; a chave do Vaga usa o link, que aqui é
                        # por página, então deduplica pelo título+data
                        k = f"{v.titulo.lower()}|{v.data_publicacao}"
                        if k in chaves:
                            continue
                        chaves.add(k)
                        vagas.append(v)
                        if len(vagas) >= max_por_fonte:
                            break
                # ponytail: teto de 6 páginas (60 páginas de diário) por termo. Cada
                # requisição leva ~1s e devolve 10 itens fixos — o PageSize não é
                # parâmetro exposto. Com ~38 termos no config, ler os 186 resultados
                # de "professor" custaria 19 requisições só nesse termo. Suba se
                # faltar vaga.
                if pagina >= 5:
                    break
                pagina += 1
    log.info("DOE-PR: %d vagas", len(vagas))
    return vagas

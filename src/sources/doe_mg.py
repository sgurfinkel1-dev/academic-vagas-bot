"""Diário Oficial do Estado de Minas Gerais (jornalminasgerais.mg.gov.br).

Por que existe: UEMG e Unimontes são estaduais e publicam edital de docente
aqui, não no DOU. O Querido Diário só cobre diário municipal, então essas vagas
não entravam por fonte nenhuma — medido em 13/08/2026, o EXTRATO DO EDITAL
UAB/UEMG 038/2026 (processo seletivo para professor regente) e o edital de
concurso para a carreira de Professor de Educação Superior da UEMG não
apareciam em nenhuma fonte do robô.

O portal é um SPA em Angular; por trás dele há uma API JSON. O contrato foi
lido do próprio bundle (main-A77B4DKJ.js) e verificado por requisição em
13/08/2026:

    POST /api/v1/Autenticacao/Autenticar   corpo {}  -> {"dados": "<JWT>"}
    GET  /api/v1/Pesquisa/PesquisarJornaisPaginados
         ?DataPublicacaoInicial=AAAA-MM-DD&DataPublicacaoFinal=AAAA-MM-DD
         &TextoPesquisa=<termo>&DiarioExecutivo=true&DiarioMunicipios=false
         &DiarioTerceiros=false&EdicaoExtra=false
         &PaginaAtual=1&TamanhoPagina=100
    -> {"dados":[{idJornal,dataPublicacao,tipoCaderno,textoResultado,pagina}],
        "paginaAtual","totalDePaginas","totalDeRegistros","erros"}

Armadilha medida: sem o header Authorization a busca devolve 401 seco (corpo
vazio, nem JSON) — não é bloqueio de bot, é só o token de sessão que o portal
emite para qualquer um, sem credencial. O POST de autenticação leva ~19 s na
primeira chamada; por isso o token é obtido uma vez e reusado na coleta toda.

Diferença dura em relação ao DOE-SP: aqui NÃO existe título nem documento. A
busca é full-text sobre o PDF da edição e devolve só um trecho de ~200
caracteres, sem acentos (extração de texto do PDF), mais a página. Todo o
filtro tem de caber nesse trecho, e o "título" da vaga é derivado dele.

Rendimento em 30 dias (13/08/2026, Diário do Executivo): professor 249
ocorrências, UEMG 93, Unimontes 91, concurso 71, magistério 36, docente 20.
"""
import json
import logging
import re
import unicodedata
import urllib.parse
from datetime import date, timedelta

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

SITE = "https://www.jornalminasgerais.mg.gov.br"
API = SITE + "/api/v1/"
CABECALHO = {"User-Agent": "academic-vagas-bot", "Content-Type": "application/json",
             "Accept": "application/json", "Origin": SITE, "Referer": SITE + "/"}

# O trecho vem sem acento ("gratificacao", "magisterio"): a extração de texto do
# PDF os perde. Por isso todo padrão daqui é escrito sem acento e o texto é
# normalizado antes de casar — tentar cobrir as duas grafias em cada regex
# dobraria o tamanho delas sem ganho.
CARGO = re.compile(r"professor|docente|magisterio|pesquisador|pos-?doutor")
FORA = re.compile(r"nomeacao|exonera|demissao|aposentadoria|licitacao|pregao|"
                  # "em virtude de aprovacao no concurso publico regido pelo
                  # Edital UEMG n 04/2024" é ato de posse, não abertura de vaga:
                  # sozinho respondia por 4 dos 9 sobreviventes do filtro.
                  r"rescisao|aprovacao no concurso|torna sem efeito")
ATO = re.compile(r"edital|concurso|processo seletivo|selecao|abertura de inscri")
# Sem ele, "Professor de Educacao Basica" da Secretaria de Educação domina: o
# Diário do Executivo de MG é, em volume, um diário de atos de pessoal da rede
# básica estadual.
SUPERIOR = re.compile(r"universidade|uemg|unimontes|educacao superior|"
                      r"magisterio superior|ensino superior")

# Medido em 13/08/2026 sobre 374 trechos únicos (termos professor, concurso,
# UEMG, Unimontes, docente; 30 dias; Diário do Executivo):
#   só cargo ............................ 140  (quase tudo rede básica/penitenciária*)
#   + ato de vaga no trecho .............  14
#   - atos barrados (FORA) ..............  10
#   + contexto de ensino superior .......   5  <- todos editais de verdade
# (*) "Penitenciaria Professor Jason Soares Albergaria" casa com CARGO: aqui o
# nome próprio da unidade é ruído estrutural, não exceção.
# Um filtro de educação básica explícito (educacao basica|peb\d|ensino medio)
# foi testado e descartou 0 itens nessa amostra — SUPERIOR já o torna redundante.

INSTITUICOES = [
    ("Universidade do Estado de Minas Gerais (UEMG)", r"uemg|universidade do estado de minas gerais"),
    ("Universidade Estadual de Montes Claros (Unimontes)", r"unimontes|universidade estadual de montes claros"),
    ("FAPEMIG", r"fapemig"),
    ("Fundação Ezequiel Dias (Funed)", r"funed|ezequiel dias"),
    ("Fundação Hemominas", r"hemominas"),
    ("Universidade Estadual de Minas Gerais", r"universidade estadual"),
]
# Tudo que sai no Diário do Executivo de MG é órgão estadual, por definição do
# veículo. Deixar clf.classificar_instituicao decidir a partir de 200 caracteres
# sem acento dava três respostas diferentes para as MESMAS duas universidades
# ("instituto público", "verificar manualmente", "pública estadual") — e vaga
# classificada errado some do filtro de tipo de instituição no painel.
CLASSE = "pública estadual"

# Onde o ato começa dentro do trecho. O corte vem antes do cabeçalho de página e
# do código de cobrança do diário ("5 cm -10 2245743 - 1"), que abrem a maioria
# dos trechos e não dizem nada.
INICIO_ATO = re.compile(
    r"(extrato do edital|edital de \w+|edital n?[o°º]?\s*[\d/]+|edital\b|"
    r"processo seletivo|concurso publico|selecao\b|aviso de \w+)")


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def _instituicao(texto: str) -> str:
    t = _sem_acento(texto)
    for nome, padrao in INSTITUICOES:
        if re.search(padrao, t):
            return nome
    return "Governo do Estado de Minas Gerais"


def _titulo(trecho: str) -> str:
    """Título sintético: a API não devolve nenhum.

    Corta o trecho no ponto em que o ato se anuncia ("EXTRATO DO EDITAL...").
    Sem isso o título viria com o lixo de paginação do PDF ("87454-9 Ibirite,
    10 de agosto de 2026 5 cm -10 2245743 - 1 ...").
    """
    limpo = re.sub(r"\s+", " ", (trecho or "")).strip()
    m = INICIO_ATO.search(_sem_acento(limpo))
    if m:
        limpo = limpo[m.start():].strip()
    return limpo[:200]


def _link(item: dict, termo: str) -> str:
    """Deep link do visualizador, montado igual ao do próprio portal.

    O botão de resultado do site chama gotoPublicacaoJornal() com este JSON em
    ?dados= — é a única forma de apontar para a página exata da edição, porque
    o PDF só é servido em base64 por endpoint autenticado.
    """
    dados = {"dataPublicacaoSelecionada": item.get("dataPublicacao") or "",
             "idCadernoEdicaoSelecionado": item.get("idJornal"),
             "paginaSelecionada": item.get("pagina"),
             "textoPesquisa": termo}
    return f"{SITE}/edicao-do-dia?dados=" + urllib.parse.quote(
        json.dumps(dados, separators=(",", ":"), ensure_ascii=False))


def _vaga(item: dict, termo: str) -> Vaga | None:
    trecho = (item.get("textoResultado") or "").strip()
    plano = _sem_acento(trecho)
    if not CARGO.search(plano) or FORA.search(plano):
        return None
    if not ATO.search(plano) or not SUPERIOR.search(plano):
        return None
    titulo = _titulo(trecho)
    prazo = clf.extrair_prazo(trecho)
    return Vaga(
        titulo=titulo,
        instituicao=_instituicao(trecho),
        classificacao_instituicao=CLASSE,
        natureza=clf.classificar_natureza(trecho),
        estado="MG",
        titulacao_exigida=clf.classificar_titulacao(trecho),
        data_publicacao=(item.get("dataPublicacao") or "")[:10],
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=_link(item, termo),
        fonte=f"DOE-MG (busca: {termo})",
        trecho_comprovacao=trecho[:600] or titulo,
        # ponytail: o trecho tem ~200 caracteres, então área, prazo e titulação
        # quase sempre ficam fora dele. Confiança média sinaliza para o
        # enriquecimento que vale abrir a edição. Suba para "alto" se algum dia
        # a API passar a devolver o ato inteiro.
        confianca="médio",
    )


def _token(cli: httpx.Client) -> str:
    """JWT de sessão do portal. Não pede credencial: o SPA chama isso no boot."""
    r = cli.post(API + "Autenticacao/Autenticar", content="{}")
    r.raise_for_status()
    return r.json().get("dados") or ""


# TextoPesquisa casa a FRASE inteira, não as palavras soltas. Medido em
# 13/08/2026, 30 dias: "professor" devolve 7 vagas; "professor substituto",
# "concurso docente" e as demais frases do config devolvem 1 no total. Como o
# config é quase todo de frases, passar a lista crua fazia a fonte parecer seca.
# Então: as âncoras de cargo entram sempre, e do que o chamador manda só
# aproveitamos as palavras únicas — que é onde vêm as áreas ("epidemiologia").
ANCORAS = ("professor", "docente", "magistério", "pesquisador")


def _termos_uteis(termos: list[str]) -> list[str]:
    unicas = [t for t in termos if t and len(t.split()) == 1]
    vistos, saida = set(), []
    for t in list(ANCORAS) + unicas:
        chave = t.lower()
        if chave not in vistos:
            vistos.add(chave)
            saida.append(t)
    return saida


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas: list[Vaga] = []
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    vistos: set[tuple] = set()
    termos = _termos_uteis(termos)
    with httpx.Client(timeout=120, headers=CABECALHO) as cli:
        try:
            token = _token(cli)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("DOE-MG: autenticação falhou (%s) — fonte vazia", e)
            return []
        if not token:
            log.warning("DOE-MG: token vazio — fonte vazia")
            return []
        cli.headers["Authorization"] = f"Bearer {token}"
        for termo in termos:
            pagina = 1
            while len(vagas) < max_por_fonte:
                params = {"DataPublicacaoInicial": inicio.isoformat(),
                          "DataPublicacaoFinal": hoje.isoformat(),
                          "TextoPesquisa": termo,
                          "DiarioExecutivo": "true", "DiarioMunicipios": "false",
                          "DiarioTerceiros": "false", "EdicaoExtra": "false",
                          "PaginaAtual": pagina, "TamanhoPagina": 100}
                try:
                    r = cli.get(API + "Pesquisa/PesquisarJornaisPaginados", params=params)
                except httpx.HTTPError as e:
                    log.warning("DOE-MG '%s' p%d: %s", termo, pagina, e)
                    break
                if r.status_code != 200:
                    log.warning("DOE-MG '%s': HTTP %d", termo, r.status_code)
                    break
                try:
                    dados = r.json()
                except ValueError:
                    log.warning("DOE-MG '%s': resposta não-JSON", termo)
                    break
                itens = dados.get("dados") or []
                if not itens:
                    break
                for it in itens:
                    # Duas duplicações reais, medidas em 13/08/2026 sobre a
                    # coleta de ['professor','concurso']: a mesma página volta
                    # em termos diferentes com o trecho deslocado (p69 da edição
                    # 330527 veio por 'professor' e por 'concurso'), e um edital
                    # longo ocupa várias páginas da mesma edição repetindo a
                    # abertura (p69 e p76 abriam com a mesma frase). Página e
                    # abertura do ato, juntas, derrubam 9 linhas para 7 sem
                    # descartar nenhum ato distinto.
                    pagina_vista = (it.get("idJornal"), it.get("pagina"))
                    if pagina_vista in vistos:
                        continue
                    vistos.add(pagina_vista)
                    v = _vaga(it, termo)
                    if not v:
                        continue
                    abertura = (it.get("idJornal"), _sem_acento(v.titulo)[:40])
                    if abertura in vistos:
                        continue
                    vistos.add(abertura)
                    vagas.append(v)
                    if len(vagas) >= max_por_fonte:
                        break
                # ponytail: teto de 3 páginas (300 trechos) por termo. "professor"
                # devolve 249 em 30 dias e a busca leva ~7 s por página; com ~38
                # termos no config, ler tudo dobraria o tempo da coleta. Suba se
                # faltar vaga.
                if pagina >= min(3, dados.get("totalDePaginas") or 1):
                    break
                pagina += 1
    log.info("DOE-MG: %d vagas", len(vagas))
    return vagas

"""Diário Oficial do Estado de Santa Catarina (doe.sea.sc.gov.br).

Por que existe: a UDESC é estadual e publica edital de docente aqui, não no DOU.
O mesmo vale para as fundações estaduais (FCEE, ENA, FAPESC) e para a ACAPS.
O Querido Diário só cobre diário municipal, então nenhuma dessas vagas entrava
por fonte alguma — medido em 13/08/2026, os PROCESSO SELETIVO 04/2026 e 05/2026
da UDESC (Professor Substituto, dezenas de áreas de conhecimento) não apareciam
em nenhuma fonte do robô.

Achar a API deu trabalho porque o portal muda de casa duas vezes:
doe.sea.sc.gov.br devolve 2.381 bytes de JavaScript que redireciona para
portal.doe.sea.sc.gov.br/v<versão>/, e ESSE é o SPA Angular de verdade. O host da
API estava no bundle main.js (`apiHost:"https://portal.doe.sea.sc.gov.br/apis"`)
e o contrato da busca no chunk lazy common.js (função `buscaMaterias`).
Contrato capturado do próprio site em 13/08/2026:

    POST https://portal.doe.sea.sc.gov.br/apis/busca-materia
    {"busca":"<termo>","dtIni":"AAAA-MM-DD","dtFim":"AAAA-MM-DD",
     "tipoBusca":2,"pagination":{"from":0,"size":25},"resumo":false,
     "aCdAssunto":[],"aCdCategoria":[]}
    -> {"total":N,"pagination":{...},"materias":[...],"busca":"..."}

Armadilha silenciosa: `resumo` é INVERTIDO — `resumo:true` devolve a publicação
SEM texto (só metadados) e `resumo:false` devolve o texto inteiro. Mandar `true`
dá 200 com resultados que não casam com filtro nenhum, o que parece "não tem
vaga" e não é. Aqui vai sempre `false`.

Rendimento em 30 dias (13/08/2026): professor 236 publicações, concurso 81.

ponytail: não há endpoint por id, então o texto integral vem junto da listagem —
tem edital de 5,5 MB no acervo. Por isso a página é pequena e o teto de páginas
é baixo; se faltar vaga, suba PAGINA/TETO_PAGINAS antes de qualquer outra coisa.
"""
import logging
import re
from datetime import date, timedelta

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

SITE = "https://portal.doe.sea.sc.gov.br"
API = SITE + "/apis/busca-materia"
# a API é aberta (sem token), mas responde melhor com Origin/Referer do portal
CABECALHO = {"User-Agent": "academic-vagas-bot", "Accept": "application/json",
             "Origin": SITE, "Referer": SITE + "/"}

PAGINA = 25          # publicações por requisição
TETO_PAGINAS = 4     # ver ponytail no topo do arquivo

# Cargo docente/pesquisa. Mesmo critério do inlabs.py e do doe_sp.py.
CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)
# Portaria de nomeação cita o concurso que nomeou, então o corpo não distingue:
# é preciso barrar pelo verbo do ato.
FORA = re.compile(r"nomea[çc][ãa]o|exonera[çc][ãa]o|demiss[ãa]o|aposentadoria|"
                  r"licita[çc][ãa]o|preg[ãa]o", re.I)
# O DOE-SC não tem campo de título, mas tem algo melhor: `assunto` é o tipo do ato
# ("EDITAL", "PORTARIA DE DESIGNAÇÃO", "ATO DE NOMEAÇÃO"), preenchido pela
# redação do diário. É o equivalente local do ATO_NO_TITULO do doe_sp.py.
ATO_DE_VAGA = re.compile(r"edital|concurso|processo seletivo|sele[çc][ãa]o|"
                         r"abertura de inscri", re.I)

# Medido em 13/08/2026 sobre 625 publicações reais (90 dias, termos professor,
# concurso, processo seletivo, docente): exigir só cargo no corpo passava 297,
# quase tudo portaria de designação/retificação da UDESC e da SED que apenas
# citam um professor. Exigir o ato em `assunto` derruba para 28; barrar o verbo
# ruim na cabeça do texto derruba para 7 — e nenhum edital de abertura se perde.
# Os 21 eliminados nesse último passo eram todos o mesmo caso: "AVISO DE
# INEXIGIBILIDADE DE LICITAÇÃO" da Escola de Governo contratando um docente
# nominal para dar um curso, que entra como assunto=EDITAL mas não é vaga.

# Seções do diário que não nomeiam órgão nenhum: nelas a instituição só existe
# dentro do texto ("O Reitor da Fundação Universidade do Estado de SC - UDESC").
CATEGORIA_GENERICA = re.compile(r"^(concursos|publica[çc][õo]es diversas|"
                                r"atos do poder executivo|secretarias de estado|"
                                r"funda[çc][õo]es estaduais|governo do estado|"
                                r"reparti[çc][õo]es federais)$", re.I)
ORGAO_NO_TEXTO = re.compile(
    r"(Funda[çc][ãa]o Universidade[^,.\n;]{0,60}|Universidade[^,.\n;]{0,50}|"
    r"Funda[çc][ãa]o [A-ZÁ-Ú][^,.\n;]{0,50}|Secretaria de Estado[^,.\n;]{0,50}|"
    r"Instituto [A-ZÁ-Ú][^,.\n;]{0,50})")

# "Término" do bloco de inscrições — é assim que a UDESC escreve o prazo, e
# extrair_prazo() não pega esse formato (procura "inscrições ... até <data>").
BLOCO_INSCRICAO = re.compile(r"per[íi]odo das inscri[çc][õo]es(.{0,900})", re.I | re.S)
TERMINO = re.compile(r"t[ée]rmino\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
# "inscrições ... de 02/06/2026 a 01/07/2026" (formato da ACAPS/SEJURI)
INTERVALO = re.compile(r"inscri[çc][õo]es?[^.]{0,200}?\d{1,2}/\d{1,2}/\d{2,4}\s*"
                       r"(?:a|at[ée])\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I | re.S)


def _cabeca(texto: str, n: int = 400) -> str:
    """Começo do texto com espaços normalizados. O tipo do ato está sempre aqui:
    o diário abre a matéria pelo cabeçalho ("AVISO DE INEXIGIBILIDADE DE
    LICITAÇÃO Nº 77/2026/ENA"). Olhar o texto inteiro só traria falso positivo —
    há edital de 5,5 MB em que qualquer palavra aparece."""
    return " ".join((texto or "").split())[:n]


def _titulo(item: dict) -> str:
    """A API não tem campo de título. As duas primeiras linhas não-vazias do
    texto são o cabeçalho do ato ("EDITAL N.º 002/2026/SEJURI/ACAPS" +
    "Processo de Seleção e Credenciamento de Servidor Docente")."""
    linhas = [l.strip() for l in (item.get("resumo") or "").split("\n") if l.strip()]
    titulo = " — ".join(linhas[:2])
    if not titulo:
        titulo = f"{item.get('assunto') or ''} — {item.get('categoria') or ''}".strip(" —")
    return re.sub(r"\s+", " ", titulo)[:200]


def _instituicao(item: dict, cabeca: str) -> str:
    categoria = (item.get("categoria") or "").strip()
    if categoria and not CATEGORIA_GENERICA.match(categoria):
        return categoria
    m = ORGAO_NO_TEXTO.search(cabeca)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip(" -–,")
    return categoria or "Governo do Estado de Santa Catarina"


def _classificar_instituicao(texto: str) -> str:
    """classificar_instituicao() erra por bug conhecido no llm_classifier: a regra
    de "instituto público" tem o padrão `ital\\b`, que casa com a palavra EDITAL.
    Como toda publicação daqui é edital, tudo virava "instituto público" (medido
    em 13/08/2026: 'EDITAL da Secretaria de Estado da Educacao' -> instituto
    público). Tirar a palavra antes de classificar resolve sem mexer no arquivo
    compartilhado. E o que sobra sem classificação é, por construção, órgão do
    governo estadual — é o diário DO ESTADO."""
    limpo = re.sub(r"\bedita(l|is)\b", " ", texto, flags=re.I)
    rotulo = clf.classificar_instituicao(limpo)
    return "pública estadual" if rotulo == "verificar manualmente" else rotulo


def _prazo(texto: str) -> str:
    """Data-limite de inscrição. Três formatos, do mais confiável ao menos."""
    prazo = clf.extrair_prazo(texto[:20000])
    if prazo:
        return prazo
    bloco = BLOCO_INSCRICAO.search(texto[:20000])
    if bloco:
        # o edital lista vários "Término" (isento, pagante); vale o último prazo
        datas = TERMINO.findall(bloco.group(1))
        if datas:
            return max(datas, key=_ordenavel)
    m = INTERVALO.search(texto[:20000])
    return m.group(1) if m else ""


def _ordenavel(d: str) -> tuple:
    dia, mes, ano = (d.split("/") + ["", "", ""])[:3]
    return (int(ano) if ano.isdigit() else 0,
            int(mes) if mes.isdigit() else 0,
            int(dia) if dia.isdigit() else 0)


def _vaga(item: dict, termo: str) -> Vaga | None:
    texto = item.get("resumo") or ""
    assunto = item.get("assunto") or ""
    cabeca = _cabeca(texto)
    if not CARGO.search(texto):
        return None
    if not ATO_DE_VAGA.search(assunto):
        return None
    if FORA.search(f"{assunto} {cabeca}"):
        return None
    # o classificador roda só no começo do edital: é onde estão cargo, titulação
    # e órgão, e onde o texto ainda não virou lista de candidatos
    inicio = texto[:6000]
    prazo = _prazo(texto)
    return Vaga(
        titulo=_titulo(item),
        instituicao=_instituicao(item, cabeca),
        classificacao_instituicao=_classificar_instituicao(
            f"{inicio} {item.get('categoria') or ''}"),
        natureza=clf.classificar_natureza(inicio),
        estado="SC",
        titulacao_exigida=clf.classificar_titulacao(inicio),
        data_publicacao=(item.get("publicacao") or "")[:10],
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=item.get("extrato") or SITE,
        fonte=f"DOE-SC (busca: {termo})",
        trecho_comprovacao=_cabeca(texto, 600) or _titulo(item),
        confianca="alto",
    )


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas: list[Vaga] = []
    vistos: set = set()
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    with httpx.Client(timeout=90, headers=CABECALHO) as cli:
        for termo in termos:
            for pagina in range(TETO_PAGINAS):
                if len(vagas) >= max_por_fonte:
                    break
                corpo = {"busca": termo,
                         "dtIni": inicio.isoformat(), "dtFim": hoje.isoformat(),
                         "tipoBusca": 2,
                         "pagination": {"from": pagina * PAGINA, "size": PAGINA},
                         "resumo": False,  # false = COM texto; ver docstring
                         "aCdAssunto": [], "aCdCategoria": []}
                try:
                    r = cli.post(API, json=corpo)
                except httpx.HTTPError as e:
                    log.warning("DOE-SC '%s' p%d: %s", termo, pagina, e)
                    break
                if r.status_code != 200:
                    log.warning("DOE-SC '%s': HTTP %d", termo, r.status_code)
                    break
                try:
                    itens = (r.json() or {}).get("materias") or []
                except ValueError as e:
                    log.warning("DOE-SC '%s': resposta não-JSON (%s)", termo, e)
                    break
                if not itens:
                    break
                for it in itens:
                    # a mesma matéria volta em vários termos; o id é da publicação
                    if it.get("id") in vistos:
                        continue
                    vistos.add(it.get("id"))
                    v = _vaga(it, termo)
                    if v:
                        vagas.append(v)
                    if len(vagas) >= max_por_fonte:
                        break
                if len(itens) < PAGINA:
                    break
    log.info("DOE-SC: %d vagas", len(vagas))
    return vagas

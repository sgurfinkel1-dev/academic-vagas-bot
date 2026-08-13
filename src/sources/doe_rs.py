"""Diário Oficial do Estado do Rio Grande do Sul (diariooficial.rs.gov.br).

Por que existe: a UERGS é universidade estadual e publica concurso docente
aqui, não no DOU; a FAPERGS (fundação estadual de fomento) publica os editais
de bolsa e de prêmio no mesmo diário. Nenhuma das duas entrava por fonte
alguma — o Querido Diário só cobre diário municipal.

O portal é um SPA em Angular (PROCERGS) e a home tem 2.685 bytes, nada de
útil. O host da API não está no bundle: o bundle busca em tempo de execução
`GET https://www.diariooficial.rs.gov.br/environments/environment.json`, que
devolve `{"restEndPoint": "https://doe-backend.pro.rs.gov.br/"}`. O contrato
foi lido do próprio bundle (main-*.js, método `MateriaService.pesquisa`) e
conferido por requisição real em 13/08/2026:

    GET https://doe-backend.pro.rs.gov.br/public/materias/
        ?page=1&tipoDiario=DOE&queryString=<frase>&tipoMateria=<tipo>
        &dataIni=AAAA-MM-DD&dataFim=AAAA-MM-DD

    -> {collection:[{id,data,texto,tipoMateria}], collectionSize, pageSize:10,
        filtroTiposMateria:{resultados:[{valor,qtdResultados}]}, filtroEntidades}

    GET https://doe-backend.pro.rs.gov.br/public/materias/<id>
    -> {nomeEntidade, nomeEntidadeCliente, nomeTipoMateria, nomeAssunto,
        dataPublicacao, conteudo (HTML), pagina, ...}

Três detalhes medidos que quebram em silêncio (200 com collectionSize=0):
  * data COM zero à esquerda (2026-08-13) — o inverso do DOE-SP;
  * tipoDiario em MAIÚSCULA ("DOE"; "DIC" é o Diário da Indústria);
  * queryString é busca por FRASE exata, não por conjunto de palavras:
    "concurso público professor" devolve 0, "concurso público" devolve 30.
    Por isso os termos aqui vão sempre soltos.

Rendimento em 30 dias (13/08/2026, tipoDiario=DOE): concurso 144 publicações,
professor 3.441, pesquisador 102, processo seletivo 37.

Limitação conhecida: a busca NÃO devolve título — só um trecho recortado em
volta do termo. O título tem de vir do cabeçalho do conteúdo, o que custa uma
requisição de detalhe por candidato. Ver `buscar`.
"""
import html
import logging
import re
from datetime import date, timedelta

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

API = "https://doe-backend.pro.rs.gov.br/public/materias/"
SITE = "https://www.diariooficial.rs.gov.br"
CABECALHO = {"User-Agent": "academic-vagas-bot", "Accept": "application/json"}

# O DOE-RS classifica cada matéria (campo `tipoMateria`), e é isso que substitui
# o "ato no título" do DOE-SP — com a vantagem de ser filtro de servidor.
# Medido em 13/08/2026, janela de 30 dias: "professor" devolve 3.441 matérias,
# das quais só 18 são Editais/Concursos (o resto é Recursos Humanos: averbação,
# licença, progressão). Sem esse filtro o teto de páginas nem alcança o edital:
# na janela de 25/10 a 05/11/2024, "professor" solto devolveu 60 matérias em 6
# páginas SEM o EDITAL DE ABERTURA DE CONCURSOS DOCENTES 2024 da UERGS
# (id 1161501); com tipoMateria=Editais ele aparece em 3 resultados.
TIPOS_ATO = ("Editais", "Concurso Público", "Concursos")

# Mesmo critério do doe_sp.py e do inlabs.py, e pela mesma razão: o termo
# pesquisado sozinho ("Direito", "Economia") casa com qualquer ato.
CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)
FORA = re.compile(r"nomea[çc][ãa]o|exonera[çc][ãa]o|demiss[ãa]o|aposentadoria|"
                  r"licita[çc][ãa]o|preg[ãa]o", re.I)
ATO_NO_TITULO = re.compile(r"edital|concurso|processo seletivo|sele[çc][ãa]o|"
                           r"abertura de inscri", re.I)

# Fase do certame. Este filtro NÃO existe no doe_sp.py e é a diferença de
# perfil de ruído entre os dois diários: em SP o lixo era portaria citando
# professor, no RS é o mesmo concurso reaparecendo a cada etapa. Medido em
# 13/08/2026 sobre 139 publicações (5 termos x 3 tipos, 30 dias): exigir cargo
# derruba para 19; exigir ato no cabeçalho não derruba NENHUMA (o tipoMateria
# já garantiu isso); exigir fase de abertura derruba para 4. Das 15 cortadas,
# 15 eram etapa posterior — homologação de resultado, cumprimento de liminar,
# convocação, retificação — inclusive os dois únicos editais da UERGS da
# janela, ambos "HOMOLOGAÇÃO DO RESULTADO FINAL".
# Contraprova em janela com abertura de verdade (25/10 a 05/11/2024): 26 -> 2
# -> 2 -> 1, e o sobrevivente é exatamente o EDITAL DE ABERTURA DE CONCURSOS
# DOCENTES 2024 da UERGS.
FASE_ENCERRADA = re.compile(
    r"homologa[çc]|resultado|classifica[çc][ãa]o|convoca[çc]|cumprimento de liminar|"
    r"retifica[çc]|revoga[çc]|isen[çc][ãa]o|deferimento|indeferi|notifica[çc][ãa]o|"
    r"sem efeito|gabarito|desclassifica|elimina[çc][ãa]o|recurso", re.I)

# O cabeçalho é onde mora o que em SP seria o título. 400 caracteres foi o que
# a medição acima usou: cobre "ÓRGÃO + CONCURSO Nº + EDITAL Nº - <ato>" com
# folga e ainda não alcança o corpo do edital, onde palavras como "recurso"
# aparecem por acaso e derrubariam vaga boa.
CABECA = 400

_TAG = re.compile(r"<[^>]+>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _texto(bruto: str) -> str:
    """HTML do campo `conteudo` -> texto corrido.

    O conteúdo vem de um editor de texto legado: tags próprias (<textopuro>),
    entidades (&nbsp;) e bytes de controle \\x01 usados como separador de
    célula de tabela. Sem limpar os três, o regex de fase e o extrator de
    prazo erram por causa de lixo no meio das palavras.
    """
    return re.sub(r"\s+", " ", _CTRL.sub(" ", html.unescape(_TAG.sub(" ", bruto or "")))).strip()


def _titulo(cabecalho: str) -> str:
    """Recorta o cabeçalho a partir do ato.

    O cabeçalho começa com o nome do órgão repetido duas ou três vezes
    ("UERGS - UNIVERSIDADE ESTADUAL DO RIO GRANDE DO SUL ESTADO DO RIO GRANDE
    DO SUL CONCURSOS PÚBLICOS Nº 02 a 24/2024 EDITAL DE ABERTURA..."). Começar
    no ato dá um título que se lê; o órgão já vai no campo instituicao.
    """
    m = ATO_NO_TITULO.search(cabecalho)
    return (cabecalho[m.start():] if m else cabecalho)[:200].strip()


def _instituicao(det: dict) -> str:
    """'Universidade Estadual do Rio Grande do Sul — Gabinete da Reitoria'."""
    orgao = (det.get("nomeEntidade") or "").strip()
    unidade = (det.get("nomeEntidadeCliente") or "").strip()
    if orgao and unidade and unidade != orgao:
        return f"{orgao} — {unidade}"
    return orgao or unidade or "Governo do Estado do Rio Grande do Sul"


def _vaga(item: dict, det: dict, termo: str) -> Vaga | None:
    """Junta resultado de busca (`item`) e detalhe (`det`) num Vaga, ou None."""
    corpo = _texto(det.get("conteudo"))
    cabecalho = corpo[:CABECA]
    if not ATO_NO_TITULO.search(cabecalho) or FASE_ENCERRADA.search(cabecalho):
        return None
    trecho = _texto(item.get("texto"))
    tudo = f"{cabecalho} {trecho} {det.get('nomeEntidade', '')}"
    if not CARGO.search(tudo) or FORA.search(tudo):
        return None
    prazo = clf.extrair_prazo(corpo)
    return Vaga(
        titulo=_titulo(cabecalho),
        instituicao=_instituicao(det),
        classificacao_instituicao=clf.classificar_instituicao(tudo),
        natureza=clf.classificar_natureza(tudo),
        estado=clf.extrair_estado(tudo) or "RS",
        titulacao_exigida=clf.classificar_titulacao(corpo),
        data_publicacao=item.get("data") or "",
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=f"{SITE}/materia?id={item.get('id')}",
        fonte=f"DOE-RS (busca: {termo})",
        trecho_comprovacao=(trecho or cabecalho)[:600],
        confianca="alto",
    )


def _busca(cli: httpx.Client, termo: str, tipo: str, pagina: int,
           inicio: date, hoje: date) -> dict:
    r = cli.get(API, params={"page": pagina, "tipoDiario": "DOE", "queryString": termo,
                             "tipoMateria": tipo, "dataIni": inicio.isoformat(),
                             "dataFim": hoje.isoformat()})
    r.raise_for_status()
    return r.json()


# `queryString` casa a FRASE inteira. Medido em 13/08/2026, 30 dias:
# "professor" devolve 4; "concurso docente", "docente" e "concurso" devolvem 0
# cada. Como o config manda quase só frases, passar a lista crua zerava a fonte.
# Mesma solução do doe_mg: âncoras de cargo sempre, e do chamador só as palavras
# únicas — que é por onde entram as áreas ("epidemiologia").
ANCORAS = ("professor", "docente", "pesquisador", "magistério")


def _termos_uteis(termos: list[str]) -> list[str]:
    unicas = [t for t in termos if t and len(t.split()) == 1]
    vistos, saida = set(), []
    for t in list(ANCORAS) + unicas:
        if t.lower() not in vistos:
            vistos.add(t.lower())
            saida.append(t)
    return saida


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Vagas acadêmicas publicadas no DOE-RS nos últimos `dias`.

    Duas fases porque a busca não devolve título: primeiro peneira o trecho da
    busca por palavra de cargo (grátis), depois paga uma requisição de detalhe
    só pelos sobreviventes. Na janela de 30 dias medida, isso foi 19 detalhes
    para 139 publicações lidas.
    """
    termos = _termos_uteis(termos)
    vagas: list[Vaga] = []
    vistos: set[int] = set()
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    with httpx.Client(timeout=60, headers=CABECALHO) as cli:
        for termo in termos:
            for tipo in TIPOS_ATO:
                pagina = 1
                while len(vagas) < max_por_fonte:
                    try:
                        dados = _busca(cli, termo, tipo, pagina, inicio, hoje)
                    except (httpx.HTTPError, ValueError) as e:
                        log.warning("DOE-RS '%s'/%s p%d: %s", termo, tipo, pagina, e)
                        break
                    itens = dados.get("collection") or []
                    if not itens:
                        break
                    for it in itens:
                        if it.get("id") in vistos:
                            continue
                        vistos.add(it.get("id"))
                        # peneira barata antes de gastar a requisição de detalhe
                        if not CARGO.search(_texto(it.get("texto"))):
                            continue
                        try:
                            det = cli.get(API + str(it["id"])).json()
                        except (httpx.HTTPError, ValueError, KeyError) as e:
                            log.warning("DOE-RS detalhe %s: %s", it.get("id"), e)
                            continue
                        v = _vaga(it, det, termo)
                        if v:
                            vagas.append(v)
                        if len(vagas) >= max_por_fonte:
                            break
                    # ponytail: teto de 5 páginas (50 publicações) por termo+tipo.
                    # "edital" sozinho tem 471 Editais em 30 dias; ler tudo para
                    # ~38 termos do config custaria mais que o resto do robô.
                    # Suba se começar a faltar vaga no fim da janela.
                    lidos = pagina * (dados.get("pageSize") or 10)
                    if pagina >= 5 or lidos >= (dados.get("collectionSize") or 0):
                        break
                    pagina += 1
    log.info("DOE-RS: %d vagas", len(vagas))
    return vagas

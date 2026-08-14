"""Diário Oficial do Estado do Rio de Janeiro (IOERJ).

Por que existe: UERJ e UENF são estaduais e publicam edital de docente aqui,
não no DOU. O Querido Diário só cobre diário municipal.

COMO SE CHEGA AO CONTEÚDO (decifrado em 13/08/2026). Não há busca por termo:
o diário é publicado como PDF e a única entrada é por data. São cinco passos,
e o quarto é ofuscado de propósito:

1. GET do_ultima_edicao.php                     -> abre sessão (PHPSESSID)
2. GET do_seleciona_edicao.php?data=<b64>       -> b64 de AAAAMMDD; lista cadernos
3. no HTML, o link "Parte I (Poder Executivo)"  -> mostra_edicao.php?session=<s>
4. nesse HTML: var pd = "<GUID>"
5. GET mostra_edicao.php?k=<pd[:12]>P<pd[12:]>  -> o PDF do caderno

O "P" do passo 5 não é enfeite. O viewer monta a URL assim, escondendo os
caracteres em String.fromCharCode para não aparecer em busca de texto:

    ...+String.fromCharCode(63)+String.fromCharCode(107)+String.fromCharCode(61)
       +pd.substring(0,12)+String.fromCharCode(80)+pd.substring(12)

que é "?" + "k" + "=" + pd[:12] + "P" + pd[12:]. Sem o P inserido na posição
12, o servidor devolve 200 com CORPO VAZIO — falha silenciosa, não erro.
(O mesmo trecho usa o char 68, "D", para baixar uma página só.)

POR QUE PyMuPDF E NÃO pdfplumber: o PDF de um dia tem 42 páginas e 4,2 MB, e
termina com marcador EOF malformado — o pypdf recusa o arquivo. Medido sobre a
edição de 13/08/2026: pdfplumber 281 s, pdfminer sem layout 318 s, PyMuPDF
1,63 s, com o mesmo texto útil. Em 30 dias isso é a diferença entre 2,6 horas e
1 minuto; é o que torna esta fonte viável.

Rendimento: a UERJ abre concurso docente em lote e esporadicamente, então mês
sem vaga é o normal — o valor está em não perder o lote quando ele sai.
"""
import base64
import logging
import re
from datetime import date, timedelta

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

BASE = "https://www.ioerj.com.br/portal/modules/conteudoonline/"
CABECALHO = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Parte I é o Poder Executivo, onde ficam as universidades estaduais. As outras
# (Tribunal de Contas, Legislativo, Municipalidades, Publicações a Pedido) não
# trazem edital de docente estadual.
CADERNO = "Parte I ("

CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)
# A UERJ abre concurso de Técnico Universitário Superior na mesma página do
# concurso docente, e o edital cita "professor" ao descrever a banca. É vaga
# real, mas não é docente — e entrava classificada como professor efetivo.
CARGO_NAO_DOCENTE = re.compile(r"t[ée]cnico universit[áa]rio|t[ée]cnico-administrativo|"
                               r"agente administrativo|auxiliar administrativo", re.I)
ATO = re.compile(r"edital|concurso p[úu]blico|processo seletivo|sele[çc][ãa]o p[úu]blica|"
                 r"abertura de inscri", re.I)
# O diário do RJ é, em volume, diário de pessoal: designação, exoneração e
# aposentadoria de professor já em exercício. Todas citam o cargo, nenhuma abre
# vaga. Sem este corte a fonte vira ruído puro.
FORA = re.compile(r"designa\b|exonera|nomeia|nomea[çc][ãa]o|aposenta|falecimento|"
                  r"licen[çc]a|averba|progress[ãa]o|licita[çc][ãa]o|preg[ãa]o", re.I)
# Só interessa quem ainda pode receber inscrição; o resto é etapa passada.
FASE_PASSADA = re.compile(r"homologa|resultado final|classifica[çc][ãa]o final|convoca", re.I)

# Uma ocorrência de "professor" e um "edital" trinta mil caracteres adiante não
# têm relação: são atos diferentes da mesma página. A janela mantém a vizinhança
# em que um ato cabe — medido: ato do DO-RJ raramente passa de 1.200 caracteres.
JANELA = 1400
UERJ_UENF = re.compile(r"\bUERJ\b|\bUENF\b|universidade do estado do rio|"
                       r"universidade estadual do norte", re.I)


def _texto_limpo(t: str) -> str:
    """Desfaz os dois estragos que a diagramação de jornal deixa no texto:
    hifenização de fim de linha ("DEPAR- TAMENTO") e letras espaçadas para
    justificar a coluna ("A D J U N TO"). Sem isto o título sai ilegível no
    painel e a regex de cargo perde ocorrência."""
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)          # DEPAR- TAMENTO -> DEPARTAMENTO
    # 3+ letras isoladas seguidas: junta. Exige o gatilho para não colar
    # iniciais legítimas ("A. B. Silva") nem siglas separadas por vírgula.
    t = re.sub(r"\b(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\s){2,}[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\b",
               lambda m: m.group(0).replace(" ", ""), t)
    return t


def _abrir(cli: httpx.Client, dia: date) -> bytes | None:
    """Devolve o PDF da Parte I do dia, ou None se não houver edição."""
    enc = base64.b64encode(dia.strftime("%Y%m%d").encode()).decode()
    r = cli.get(BASE + "do_seleciona_edicao.php", params={"data": enc})
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    link = next((a["href"] for a in soup.find_all("a", href=True)
                 if CADERNO in a.get_text(" ", strip=True)), None)
    if not link:  # fim de semana e feriado não têm edição
        return None
    html = cli.get(BASE + link).text
    m = re.search(r'var\s+pd\s*=\s*"([^"]+)"', html)
    if not m:
        log.warning("DOE-RJ %s: 'var pd' sumiu do HTML — o portal mudou", dia)
        return None
    pd = m.group(1)
    r2 = cli.get(BASE + "mostra_edicao.php", params={"k": pd[:12] + "P" + pd[12:]})
    if r2.status_code != 200 or not r2.content.startswith(b"%PDF"):
        log.warning("DOE-RJ %s: não veio PDF (%d, %d bytes)",
                    dia, r2.status_code, len(r2.content))
        return None
    return r2.content


def _atos(pdf: bytes) -> list[str]:
    """Cada trecho é a vizinhança de uma menção a cargo docente."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception as e:
        log.warning("DOE-RJ: PDF ilegível: %s", e)
        return []
    with doc:
        texto = _texto_limpo("\n".join(p.get_text() for p in doc))
    vistos, saida = set(), []
    for m in CARGO.finditer(texto):
        ini = max(0, m.start() - JANELA // 2)
        trecho = texto[ini:m.start() + JANELA // 2]
        chave = trecho[:120]
        if chave not in vistos:
            vistos.add(chave)
            saida.append(trecho)
    return saida


def _vaga(trecho: str, dia: date) -> Vaga | None:
    if not ATO.search(trecho) or FORA.search(trecho) or FASE_PASSADA.search(trecho):
        return None
    # Sem UERJ/UENF no trecho é quase sempre a rede estadual de ensino básico,
    # que não é vaga acadêmica e polui o painel.
    if not UERJ_UENF.search(trecho):
        return None
    # O cabeçalho do ato vem em caixa alta neste diário. Ancorar nele evita
    # começar a vaga no meio de uma frase — sem isto entrava "Edital; d)
    # preencher, de acordo com as instruções..." como se fosse um edital.
    m = (re.search(r"(EDITAL|CONCURSO P[ÚU]BLICO|PROCESSO SELETIVO)", trecho)
         or re.search(r"(Processo Seletivo|Concurso P[úu]blico)", trecho))
    if m is None:
        return None
    # A prova tem de começar onde o ato começa. Antes o título vinha do ato e o
    # trecho vinha da janela crua, que costuma abrir no meio do ato anterior —
    # a vaga aparecia no painel com um extrato de contrato como comprovação.
    corpo = trecho[m.start():]
    titulo = _texto_limpo(corpo[:130])
    if CARGO_NAO_DOCENTE.search(titulo):
        return None
    prazo = clf.extrair_prazo(corpo)
    return Vaga(
        titulo=titulo[:200],
        instituicao=("Universidade do Estado do Rio de Janeiro (UERJ)"
                     if re.search(r"\bUERJ\b|universidade do estado do rio", trecho, re.I)
                     else "Universidade Estadual do Norte Fluminense (UENF)"),
        # Tudo aqui é Parte I do diário estadual: órgão estadual por definição do
        # veículo. Deixar o classificador adivinhar a partir de um trecho solto
        # devolvia respostas diferentes para a mesma universidade.
        classificacao_instituicao="pública estadual",
        natureza=clf.classificar_natureza(corpo),
        estado="RJ",
        titulacao_exigida=clf.classificar_titulacao(corpo),
        data_publicacao=dia.strftime("%d/%m/%Y"),
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=BASE + "do_seleciona_edicao.php?data=" +
                     base64.b64encode(dia.strftime("%Y%m%d").encode()).decode(),
        fonte="DOE-RJ (Parte I)",
        trecho_comprovacao=_texto_limpo(corpo[:600]),
        # O trecho vem de PDF de jornal, com colunas intercaladas: o texto é
        # legível mas às vezes embaralha o fim de uma frase com o começo de
        # outra. Confere no link antes de se inscrever.
        confianca="médio",
    )


def buscar(termos: list[str] | None = None, dias: int = 30,
           max_por_fonte: int = 100) -> list[Vaga]:
    """`termos` é ignorado: o IOERJ não tem busca por palavra, só por data.
    A assinatura fica igual à das outras fontes para o main.py tratar todas do
    mesmo jeito."""
    vagas: list[Vaga] = []
    hoje = date.today()
    with httpx.Client(timeout=120, headers=CABECALHO, follow_redirects=True) as cli:
        try:
            cli.get(BASE + "do_ultima_edicao.php")  # abre a sessão
        except httpx.HTTPError as e:
            log.warning("DOE-RJ: não abriu sessão: %s", e)
            return []
        for n in range(dias):
            dia = hoje - timedelta(days=n)
            if dia.weekday() > 4:  # sábado e domingo não têm edição
                continue
            try:
                pdf = _abrir(cli, dia)
            except httpx.HTTPError as e:
                log.warning("DOE-RJ %s: %s", dia, e)
                continue
            if not pdf:
                continue
            for trecho in _atos(pdf):
                v = _vaga(trecho, dia)
                if v:
                    vagas.append(v)
                if len(vagas) >= max_por_fonte:
                    log.info("DOE-RJ: teto de %d atingido em %s", max_por_fonte, dia)
                    return vagas
    log.info("DOE-RJ: %d vagas", len(vagas))
    return vagas

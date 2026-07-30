"""Classificação por regras (sem LLM — grátis e determinístico).
ponytail: se as regras errarem muito, plugue um LLM aqui mantendo a mesma assinatura.
"""
import re
from datetime import date, datetime

REGRAS_INSTITUICAO = [
    ("pública federal", r"universidade federal|instituto federal|cefet|fundação universidade federal|\buf[a-z]{1,4}\b|\bif[a-z]{2,10}\b|colégio pedro ii"),
    ("pública estadual", r"universidade estadual|universidade de são paulo|\busp\b|unicamp|unesp|uerj|uenf|uem\b|uel\b|uepg|udesc|uneb|uece|upe\b|uema|unemat|unespar|fatec|famerp|famema"),
    ("pública municipal", r"universidade municipal|fundação municipal|autarquia municipal|centro universitário municipal|uscs\b|prefeitura"),
    ("instituto público", r"fiocruz|butantan|inpe\b|inpa\b|impa\b|cnpem|embrapa|ipea\b|ibict|cbpf|lncc|ital\b|instituto de pesquisas? (energéticas|tecnológicas)"),
    ("agência/fundação", r"fapesp|faperj|fapemig|facepe|fapergs|fapeam|fapesb|fundação araucária|capes\b|cnpq\b"),
    ("privada", r"pontifícia|católica|mackenzie|\bfgv\b|insper|einstein|sírio.libanês|senac|senai|estácio|anhanguera|unip\b|uninove|cruzeiro do sul|ibmec"),
]

REGRAS_NATUREZA = [
    ("professor visitante", r"professor visitante"),
    ("professor colaborador", r"professor colaborador"),
    ("professor substituto", r"professor substituto|professor temporário|processo seletivo simplificado"),
    ("professor efetivo (concurso público)", r"concurso público|concurso docente|professor efetivo|magistério superior|carreira docente"),
    ("pós-doutorado", r"pós.doutor|postdoc|post.doctoral"),
    ("bolsa", r"\bbolsa\b|bolsista|fellowship"),
    ("pesquisador", r"pesquisador|research (fellow|position)"),
    ("docente (outros)", r"docente|professor|faculty"),
]

REGRAS_TITULACAO = [
    ("livre-docência", r"livre.doc"),
    ("pós-doutorado", r"pós.doutorado concluído"),
    ("doutorado", r"doutor(ado)?\b"),
    ("mestrado", r"mestr(e|ado)\b"),
    ("graduação", r"graduação|graduado"),
]


# Área do conhecimento. Ordem importa: a primeira que casar vence, então os termos
# mais específicos vêm antes (lógica antes de filosofia, direito antes de humanas).
REGRAS_AREA = [
    ("lógica", r"\bl[óo]gica\b"),
    ("filosofia", r"filosofi|\bética\b|epistemolog|metafísic|fenomenolog|hermenêutic|estétic"),
    ("direito", r"\bdireito\b|jurídic|\bjurídica\b|ciências jurídicas"),
    ("medicina", r"\bmedicina\b|\bmédic[ao]\b|clínica médica|cirurgi|patologi"),
    ("enfermagem", r"enfermage"),
    ("farmácia", r"farm[áa]ci|farmacolog"),
    ("odontologia", r"odontolog"),
    ("psicologia", r"psicolog"),
    ("educação", r"\bpedagogi|educação|ensino de\b|didátic"),
    ("história", r"\bhistória\b|historiograf"),
    ("letras/linguística", r"\bletras\b|linguístic|literatura|língua portuguesa|língua inglesa"),
    ("sociologia/antropologia", r"sociolog|antropolog|ciências sociais"),
    ("ciência política", r"ciência política|relações internacionais"),
    ("economia", r"\beconomia\b|econômic|contábe|contabilidade"),
    ("administração", r"administração|\bgestão\b|marketing|recursos humanos"),
    ("computação", r"computação|\binformática\b|engenharia de software|ciência da computação|"
                   r"inteligência artificial|ciência de dados|sistemas de informação"),
    ("matemática", r"matemátic|estatístic"),
    ("física", r"\bfísica\b"),
    ("química", r"\bquímica\b|químic[ao]\b"),
    ("biologia", r"biologi|biociênc|ciências biológicas|genétic|ecologi"),
    ("engenharia", r"engenharia"),
    ("arquitetura/urbanismo", r"arquitetur|urbanismo"),
    ("agrárias", r"agronomi|veterinári|zootecni|ciências agrárias|agronegóci"),
    ("comunicação", r"\bjornalismo\b|comunicação social|publicidade"),
    ("artes", r"\bartes\b|artes visuais|\bmúsica\b|\bteatro\b|\bdança\b"),
    ("educação física", r"educação física"),
]


# No corpo de um edital a palavra da área aparece solta em qualquer contexto
# ("continuidade lógica", "argumentação lógica"). Só vale quando vem onde o edital
# de fato declara a área da vaga.
CONTEXTO_AREA = re.compile(
    r"(?:[áa]reas?(?:\s+de\s+conhecimento)?|setor\s+de\s+estudos?|departamento|"
    r"curso|disciplinas?|programa\s+de\s+p[óo]s.?gradua[çc][ãa]o)"
    r"\s*(?:de|em|:)\s*([^.;\n]{3,60})", re.I)


def classificar_area(titulo: str, corpo: str = "") -> str:
    """Área do conhecimento; '' quando nada casa (melhor vazio que errado).
    O título vale por si; no corpo, só conta se estiver declarando a área da vaga."""
    area = _primeira(REGRAS_AREA, titulo, "")
    if area:
        return area
    for m in CONTEXTO_AREA.finditer(corpo or ""):
        area = _primeira(REGRAS_AREA, m.group(1), "")
        if area:
            return area
    return ""


def _primeira(regras, texto, default):
    t = texto.lower()
    for rotulo, padrao in regras:
        if re.search(padrao, t):
            return rotulo
    return default


def classificar_instituicao(texto: str) -> str:
    return _primeira(REGRAS_INSTITUICAO, texto, "verificar manualmente")


def classificar_natureza(texto: str) -> str:
    return _primeira(REGRAS_NATUREZA, texto, "não informado")


def classificar_titulacao(texto: str) -> str:
    return _primeira(REGRAS_TITULACAO, texto, "não informado")


def extrair_prazo(texto: str) -> str:
    m = re.search(r"inscri[çc][õo]es?.{0,40}?at[ée]\s+(\d{1,2}[/.]\d{1,2}[/.]\d{2,4})", texto, re.I | re.S)
    if not m:
        m = re.search(r"prazo.{0,30}?(\d{1,2}[/.]\d{1,2}[/.]\d{2,4})", texto, re.I | re.S)
    return m.group(1).replace(".", "/") if m else ""


def status_por_prazo(prazo: str) -> str:
    if not prazo:
        return "sem prazo identificado"
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return "aberta" if datetime.strptime(prazo, fmt).date() >= date.today() else "vencida"
        except ValueError:
            continue
    return "sem prazo identificado"


# --- validador central: só vaga aberta de docência/pesquisa em ensino superior ---
EXCLUIR = re.compile(
    r"educação infantil|ensino fundamental|ensino médio|educação básica|\beja\b|creche|berçário|"
    r"professor de apoio|auxiliar de classe|professor i\b|peb.i|"
    r"extratos? d[eo]s? (contratos?|termos?|doaç|acordos?|rescis|registros?|convênios?|instrumento)|"
    r"termo aditivo|aviso de licitação|apostilamento|"
    r"resultado final|homologação|nomeação|convocação|aposentadoria|exoneração|"
    r"relação de cursos|pós em\b|inscreva-se no curso", re.I)
CARGO = re.compile(r"professor|docente|pesquisador|pós.doutor|postdoc|bolsista|magistério superior|lecturer", re.I)
CONTEXTO_SUPERIOR = re.compile(
    r"universi|faculdade|instituto|centro universitário|ensino superior|magistério superior|"
    r"pós.gradua|campus|pós.doutor|postdoc|fapesp|capes|cnpq", re.I)


def eh_vaga_academica(texto: str, classificacao: str = "") -> bool:
    """True somente para vaga aberta de professor/pesquisador de ensino superior."""
    if EXCLUIR.search(texto):
        return False
    if not CARGO.search(texto):
        return False
    # diários municipais publicam sobretudo educação básica: exige contexto de ensino superior
    if classificacao in ("pública municipal", "verificar manualmente") and not CONTEXTO_SUPERIOR.search(texto):
        return False
    return True


def extrair_estado(texto: str) -> str:
    m = re.search(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b", texto)
    return m.group(1) if m else ""

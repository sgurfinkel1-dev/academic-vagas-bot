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


def extrair_estado(texto: str) -> str:
    m = re.search(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b", texto)
    return m.group(1) if m else ""

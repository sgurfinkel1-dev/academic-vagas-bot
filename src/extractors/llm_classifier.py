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
    # "concurso público" sozinho NÃO é vaga de professor — técnico-administrativo também
    # é concurso público. Exige o cargo docente por perto, senão a natureza inventava um
    # "professor" que depois fazia eh_vaga_academica aprovar o edital (raciocínio circular).
    ("professor efetivo (concurso público)",
     r"concurso p[úu]blico[^.]{0,80}?(?:professor|docente|magist[ée]rio)|"
     r"(?:professor|docente|magist[ée]rio)[^.]{0,80}?concurso p[úu]blico|"
     r"concurso docente|professor efetivo|magistério superior|carreira docente"),
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


# "Faculdade de Filosofia, Letras e Ciências Humanas" é o nome da CASA, não a área:
# uma vaga de História na FFLCH não é vaga de filosofia. Idem "Escola de Filosofia".
# "Faculdade/Escola de Filosofia" é unidade guarda-chuva (FFLCH, EFLCH): abriga História,
# Comunicação, Letras. Já "Departamento de Filosofia" é a área da vaga — esse fica.
NOME_DE_CASA = re.compile(
    r"(?:faculdade|escola)\s+de\s+filosofia(?:\s*,?\s*"
    r"(?:letras|ci[êe]ncias|artes|educa[çc][ãa]o)[^.;]{0,40})?|"
    r"instituto\s+de\s+filosofia\s*(?:e|,)\s*ci[êe]ncias", re.I)


def _sem_nome_de_casa(texto: str) -> str:
    return NOME_DE_CASA.sub(" ", texto or "")


def classificar_area(titulo: str, corpo: str = "") -> str:
    """Área do conhecimento; '' quando nada casa (melhor vazio que errado).
    O título vale por si; no corpo, só conta se estiver declarando a área da vaga."""
    area = _primeira(REGRAS_AREA, _sem_nome_de_casa(titulo), "")
    if area:
        return area
    for m in CONTEXTO_AREA.finditer(_sem_nome_de_casa(corpo)):
        area = _primeira(REGRAS_AREA, m.group(1), "")
        if area:
            return area
    return ""


# o edital costuma declarar a área literal: "Área: Filosofia Subárea: Filosofia Política",
# "Área de Conhecimento: Filosofia Clássica Alemã", "Setor de estudo: Lógica"
ROTULO_AREA = re.compile(
    r"(sub[ -]?[áa]rea|[áa]rea\s+de\s+conhecimento|setor\s+de\s+estudos?|[áa]reas?|departamento)"
    r"\s*:?\s*(?:d[eoa]s?\s+|em\s+)?[\"“]?", re.I)
# a captura corre até o próximo rótulo do edital; corta aí para não colar dois campos
CORTA_ROTULO = re.compile(
    r"\s+(?:sub[ -]?[áa]rea|[áa]rea|departamento|setor|edital|n[ºo°]\b|regime|vagas?|"
    r"processo|classe|campus|per[íi]odo|inscri|requisito|titula[çc])\b.*$", re.I)
# quanto mais específico o rótulo, melhor a declaração
PESO_ROTULO = {"sub": 4, "área de conhecimento": 3, "area de conhecimento": 3,
               "setor de estudo": 3, "setor de estudos": 3, "área": 2, "area": 2,
               "departamento": 1}


def _peso(rotulo: str) -> int:
    r = rotulo.lower().strip()
    return 4 if r.startswith("sub") else PESO_ROTULO.get(r, 1)


def extrair_subarea(corpo: str) -> str:
    """O que o edital declara como área/subárea da vaga, na letra dele.
    Fica com a declaração de rótulo mais específico ("Subárea" ganha de "Área")."""
    texto = _sem_nome_de_casa(corpo or "")
    marcas = list(ROTULO_AREA.finditer(texto))
    melhor, melhor_peso = "", 0
    for i, m in enumerate(marcas):
        # até o próximo rótulo: senão "Área: X Subárea: Y" cola os dois campos
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        valor = re.split(r"[.;:\n\"”]", texto[m.end():fim])[0]
        valor = CORTA_ROTULO.sub("", valor).strip(" -–,\"”")
        valor = re.sub(r"\s+(?:d[eoa]s?|e|em|na|no|,)\s*$", "", valor, flags=re.I)  # conector solto no fim
        if len(valor) < 4:
            continue
        p = _peso(m.group(1))
        if p > melhor_peso:
            melhor, melhor_peso = re.sub(r"\s+", " ", valor), p
    return melhor[:120]


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
    r"relação de cursos|pós em\b|inscreva-se no curso|"
    # concursos de servidor não-docente: o app é só de professor/pesquisador.
    # (não pega "Ensino Básico, Técnico e Tecnológico", que é carreira docente do IF)
    r"t[ée]cnico.administrativ|carreira t[ée]cnic|cargos? t[ée]cnicos?|"
    r"assistente em administra|t[ée]cnico de laborat[óo]rio|técnico de tecnologia", re.I)
# post.?doc cobre postdoc, post-doc e "post-doctoral fellowship" (FAPESP publica em inglês).
# "Prof." / "Profa." abreviado é comum nos anúncios da ANPOF ("Seleção Prof visitante pleno").
CARGO = re.compile(r"professor|\bprofa?\b\.?|docente|pesquisador|pós.doutor|post.?doc|bolsista|"
                   r"magistério superior|lecturer|research fellow", re.I)
CONTEXTO_SUPERIOR = re.compile(
    r"universi|faculdade|instituto|centro universitário|ensino superior|magistério superior|"
    r"pós.gradua|campus|pós.doutor|postdoc|fapesp|capes|cnpq", re.I)


# Fontes que, por construção, só publicam vaga de ensino superior. Nelas o anúncio é
# curto ("Concurso para professor efetivo em Filosofia Política — Uberlândia/MG") e não
# repete a palavra "universidade": exigir isso descartaria vaga boa.
FONTE_SO_SUPERIOR = re.compile(r"ANPOF|FAPESP", re.I)


def eh_vaga_academica(texto: str, classificacao: str = "", fonte: str = "") -> bool:
    """True somente para vaga aberta de professor/pesquisador de ensino superior."""
    if EXCLUIR.search(texto):
        return False
    if not CARGO.search(texto):
        return False
    # diários municipais publicam sobretudo educação básica: exige contexto de ensino superior
    if (classificacao in ("pública municipal", "verificar manualmente")
            and not FONTE_SO_SUPERIOR.search(fonte)
            and not CONTEXTO_SUPERIOR.search(texto)):
        return False
    return True


def extrair_estado(texto: str) -> str:
    m = re.search(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b", texto)
    return m.group(1) if m else ""

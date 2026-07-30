"""Sinônimos de subárea, para a busca do painel.

Editais escrevem a mesma coisa de jeitos diferentes: quem procura "epistemologia"
quer também "teoria do conhecimento"; quem procura "ética" quer "filosofia moral".
Cada grupo abaixo conta como UM termo na busca — casar qualquer forma do grupo vale
o mesmo. Foco em filosofia, que é a área de quem usa o painel.

ponytail: mapa escrito à mão. Se um dia cobrir muitas áreas, troque por embeddings
mantendo a assinatura de expandir().
"""
import unicodedata

# palavras genéricas: aparecem em quase toda vaga, só atrapalham o casamento
GENERICAS = {"concurso", "professor", "professora", "professores", "vaga", "vagas",
             "docente", "docentes", "edital", "publico", "publica", "universidade",
             "de", "da", "do", "dos", "das", "para", "em", "e", "no", "na"}

GRUPOS = [
    # --- filosofia: subáreas e seus nomes alternativos ---
    ["lógica", "filosofia da lógica", "lógica matemática", "lógica formal"],
    ["epistemologia", "teoria do conhecimento", "gnosiologia"],
    ["ética", "filosofia moral", "filosofia prática"],
    ["metafísica", "ontologia", "filosofia primeira"],
    ["estética", "filosofia da arte"],
    ["filosofia política", "teoria política", "filosofia social"],
    ["filosofia da mente", "ciências cognitivas", "ciência cognitiva"],
    ["filosofia da ciência", "epistemologia da ciência"],
    ["filosofia da linguagem", "semântica filosófica"],
    ["fenomenologia", "existencialismo"],
    ["filosofia antiga", "filosofia grega", "filosofia clássica"],
    ["filosofia medieval", "escolástica", "patrística"],
    ["filosofia moderna", "racionalismo", "empirismo"],
    ["filosofia contemporânea", "filosofia analítica", "teoria crítica"],
    ["filosofia do direito", "teoria do direito", "jusfilosofia", "filosofia jurídica"],
    ["filosofia da religião", "teologia filosófica"],
    ["ensino de filosofia", "filosofia da educação"],
    # --- fora da filosofia, os casos que mais aparecem ---
    ["inteligência artificial", "aprendizado de máquina", "machine learning",
     "ciência de dados", "aprendizagem de máquina"],
    ["computação", "ciência da computação", "informática", "sistemas de informação"],
    ["letras", "linguística", "literatura"],
    ["sociologia", "antropologia", "ciências sociais"],
]


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


_GRUPOS_NORM = [sorted({sem_acento(f) for f in g}, key=len, reverse=True) for g in GRUPOS]


def expandir(consulta: str) -> list[list[str]]:
    """Consulta -> lista de grupos de formas equivalentes; cada grupo conta como UM termo.

    "filosofia da lógica" -> [["logica", "filosofia da logica", ...], ["filosofia"]]
    "epistemologia"       -> [["epistemologia", "teoria do conhecimento", "gnosiologia"]]
    """
    q = sem_acento(consulta)
    grupos, usadas = [], set()
    for formas in _GRUPOS_NORM:
        achada = next((f for f in formas if f in q), None)  # formas longas primeiro
        if achada:
            grupos.append(formas)
            usadas.update(achada.split())
    for palavra in q.split():
        if palavra in usadas or palavra in GENERICAS:
            continue
        grupos.append([palavra])
        usadas.add(palavra)
    return grupos or [[p] for p in q.split()]

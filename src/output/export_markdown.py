from pathlib import Path

SAIDA = Path(__file__).resolve().parents[2] / "data" / "processed"

SECOES = [
    ("Públicas federais", ["pública federal"]),
    ("Públicas estaduais", ["pública estadual"]),
    ("Públicas municipais", ["pública municipal"]),
    ("Institutos públicos", ["instituto público"]),
    ("Privadas", ["privada", "instituto privado"]),
    ("Bolsas / pós-doc / agências", ["agência/fundação"]),
    ("Verificar manualmente", ["verificar manualmente"]),
]


def exportar(vagas: list[dict]) -> Path:
    linhas = ["# Vagas acadêmicas encontradas\n"]
    for titulo, classes in SECOES:
        grupo = [v for v in vagas if v.get("classificacao_instituicao") in classes]
        if not grupo:
            continue
        linhas += [f"\n## {titulo} ({len(grupo)})\n",
                   "| Vaga | Instituição | Área | Prazo | Status | Link |",
                   "|---|---|---|---|---|---|"]
        for v in grupo:
            t = v.get("titulo", "").replace("|", "/")[:80]
            linhas.append(f"| {t} | {v.get('instituicao','')} | {v.get('area','')} | "
                          f"{v.get('prazo_inscricao','')} | {v.get('status','')} | "
                          f"[link]({v.get('link_oficial','')}) |")
    destino = SAIDA / "vagas.md"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino

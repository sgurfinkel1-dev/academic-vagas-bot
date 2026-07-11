"""Orquestrador: roda as fontes ligadas no config, filtra, deduplica, salva,
exporta (MD/CSV/JSON) e alerta sobre vagas novas.

Uso:  python -m src.main [--config config.yaml]
"""
import argparse
import logging
import sys
from pathlib import Path

import yaml

from .database import storage
from .database.models import Vaga
from .sources import dou, querido_diario, fapesp, universidades_publicas, universidades_privadas, busca_aberta, gupy, vagas_com
from .alerts import telegram_alert, discord_alert, email_alert
from .output import export_csv, export_json, export_markdown

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bot")

CLASSE_FILTRO = {
    "publica_federal": "pública federal", "publica_estadual": "pública estadual",
    "publica_municipal": "pública municipal", "privada": "privada",
}


def filtrar(vagas: list[Vaga], user: dict) -> list[Vaga]:
    classes_ok = {CLASSE_FILTRO[i] for i in user.get("instituicoes", []) if i in CLASSE_FILTRO}
    # institutos, agências e "verificar manualmente" sempre passam — melhor sobrar que faltar
    classes_ok |= {"instituto público", "instituto privado", "agência/fundação", "verificar manualmente"}
    estados = set(user.get("estados", []))
    saida = []
    for v in vagas:
        if v.classificacao_instituicao not in classes_ok:
            continue
        if estados and v.estado and v.estado not in estados:
            continue
        if not user.get("incluir_vencidas", False) and v.status == "vencida":
            continue
        saida.append(v)
    return saida


def montar_alerta(novas: list[Vaga], user: dict) -> str:
    linhas = [f"🎓 {len(novas)} nova(s) vaga(s) acadêmica(s):\n"]
    for v in novas[:15]:
        linhas.append(
            f"• {v.titulo[:90]}\n  {v.instituicao} ({v.classificacao_instituicao})"
            f" | área: {v.area or '-'} | prazo: {v.prazo_inscricao or 'ver edital'}\n  {v.link_oficial}\n"
            f"  Motivo: bate com filtros ({', '.join(user.get('areas', [])) or 'geral'})\n")
    if len(novas) > 15:
        linhas.append(f"... e mais {len(novas) - 15}. Veja data/processed/vagas.md")
    return "\n".join(linhas)


def _buscar_palavra(palavra: str, cfg: dict, modo: str = "geral") -> int:
    """Busca ao vivo por uma palavra/área e salva no banco.
    modo 'geral': privadas (Gupy) + diários municipais (rápido).
    modo 'diarios': DOU (navegador, lento) + diários municipais."""
    dias = max(cfg["busca"].get("dias_retroativos", 30), 90)  # janela ampla p/ área específica
    vagas = []
    if modo == "diarios":
        vagas += dou.buscar_palavra(palavra, dias)
    else:
        vagas += gupy.buscar([palavra])
    qd = querido_diario.buscar([palavra], dias, 100, estados=cfg["usuario"].get("estados") or None)
    for v in qd:
        v.area = palavra
    vagas += qd
    con = storage.conectar()
    novas = storage.salvar(con, vagas)
    export_csv.exportar(storage.todas(con))
    export_json.exportar(storage.todas(con))
    export_markdown.exportar(storage.todas(con))
    print(f"Busca '{palavra}': {len(vagas)} encontradas, {len(novas)} novas.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.yaml"))
    ap.add_argument("--palavra", help="busca ao vivo por esta palavra/área (ex.: Direito)")
    ap.add_argument("--modo", default="geral", choices=["geral", "diarios"])
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    if args.palavra:
        return _buscar_palavra(args.palavra, cfg, args.modo)

    user, busca, fontes = cfg["usuario"], cfg["busca"], cfg["fontes"]
    termos = cfg.get("termos_base", []) + [a for a in user.get("areas", [])]
    dias = busca.get("dias_retroativos", 30)
    max_f = busca.get("max_resultados_por_fonte", 100)

    todas_vagas, falhas = [], []
    execucoes = [
        ("dou", lambda: dou.buscar(cfg.get("termos_base", []), dias, max_f)),
        ("querido_diario", lambda: querido_diario.buscar(cfg.get("termos_base", []), dias, max_f,
                                                         estados=user.get("estados") or None)),
        ("fapesp", lambda: fapesp.buscar(user.get("areas", []), max_f)),
        ("universidades_publicas", lambda: universidades_publicas.buscar(cfg.get("paginas_concursos", []), max_f)),
        ("universidades_privadas", lambda: universidades_privadas.buscar(cfg.get("paginas_privadas", []), max_f)),
        ("busca_aberta", lambda: busca_aberta.buscar(cfg.get("termos_base", []), user.get("areas", []), 50)),
        ("gupy", lambda: gupy.buscar(user.get("areas", []), max_f)),
        ("vagas_com", lambda: vagas_com.buscar(max_f)),
    ]
    for nome, fn in execucoes:
        if not fontes.get(nome, False):
            continue
        log.info("fonte: %s ...", nome)
        try:
            encontradas = fn()
            log.info("  %d resultado(s)", len(encontradas))
            todas_vagas += encontradas
        except Exception as e:
            log.error("  fonte %s falhou: %s", nome, e)
            falhas.append(nome)

    aprovadas = filtrar(todas_vagas, user)

    con = storage.conectar()
    novas = storage.salvar(con, aprovadas)
    registros = storage.todas(con)

    export_csv.exportar(registros)
    export_json.exportar(registros)
    export_markdown.exportar(registros)

    if novas:
        msg = montar_alerta(novas, user)
        canal = user.get("alerta", {}).get("canal", "nenhum")
        alertas_cfg = cfg.get("alertas", {})
        {"telegram": lambda: telegram_alert.enviar(msg, alertas_cfg.get("telegram", {})),
         "discord": lambda: discord_alert.enviar(msg, alertas_cfg.get("discord", {})),
         "email": lambda: email_alert.enviar(msg, alertas_cfg.get("email", {})),
         }.get(canal, lambda: log.info("alerta desativado"))()

    # resumo final
    abertas = [r for r in registros if r["status"] == "aberta"]
    publicas = [r for r in registros if r["classificacao_instituicao"].startswith("pública")]
    privadas = [r for r in registros if r["classificacao_instituicao"] == "privada"]
    bolsas = [r for r in registros if r["classificacao_instituicao"] == "agência/fundação"
              or r["natureza"] in ("bolsa", "pós-doutorado")]
    print("\n===== RESUMO =====")
    print(f"Total no banco:        {len(registros)}")
    print(f"Novas nesta execução:  {len(novas)}")
    print(f"Abertas:               {len(abertas)}")
    print(f"Públicas:              {len(publicas)}")
    print(f"Privadas:              {len(privadas)}")
    print(f"Pós-doc/bolsas:        {len(bolsas)}")
    proximas = sorted((r for r in abertas if r["prazo_inscricao"]), key=lambda r: r["prazo_inscricao"][::-1])[:5]
    for r in proximas:
        print(f"  prazo {r['prazo_inscricao']}: {r['titulo'][:70]}")
    if falhas:
        print(f"Fontes que falharam:   {', '.join(falhas)}")
    print("Saídas: data/processed/vagas.{md,csv,json,db} | dashboard: streamlit run dashboard.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

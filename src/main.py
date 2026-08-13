"""Orquestrador: roda as fontes ligadas no config, filtra, deduplica, salva,
exporta (MD/CSV/JSON) e alerta sobre vagas novas.

Uso:  python -m src.main [--config config.yaml]
"""
import argparse
import logging
import re
import sys
from pathlib import Path

import yaml

from . import assinaturas
from .database import storage
from .database.models import Vaga
from .extractors import llm_classifier as clf
from .sources import (dou, querido_diario, fapesp, universidades_publicas, universidades_privadas,
                      busca_aberta, gupy, vagas_com, anpof, inlabs, doe_sp, doe_rj, doe_mg, doe_outros_estados)
from .alerts import telegram_alert, discord_alert, email_alert
from .output import export_csv, export_json, export_markdown

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bot")

CLASSE_FILTRO = {
    "publica_federal": "pública federal", "publica_estadual": "pública estadual",
    "publica_municipal": "pública municipal", "privada": "privada",
}


# Título que é só a referência do ato ("EDITAL Nº 1584, DE 2 DE JULHO DE 2026"):
# comum no DOU e ilegível na listagem — remontamos a partir do que foi classificado.
SO_REFERENCIA = re.compile(r"^\s*(edital|aviso|portaria|retifica[çc][ãa]o|extrato)\b", re.I)
CARGO_NO_TITULO = re.compile(r"professor|docente|pesquisador|p[óo]s.doutor|bolsa|magist[ée]rio", re.I)


def _enriquecer(v: Vaga) -> Vaga:
    """Preenche a área e torna o título legível. Roda para toda vaga, de qualquer fonte."""
    if not (v.area or "").strip():
        v.area = clf.classificar_area(f"{v.titulo} {v.area or ''}", v.trecho_comprovacao)
    if not (v.subarea or "").strip():
        v.subarea = clf.extrair_subarea(v.trecho_comprovacao)
    if SO_REFERENCIA.match(v.titulo) and not CARGO_NO_TITULO.search(v.titulo):
        cargo = v.natureza if v.natureza != "não informado" else "Vaga docente"
        rotulo = f"{cargo} em {v.area}" if v.area else cargo
        ref = re.sub(r",?\s*DE\s+\d.*$", "", v.titulo, flags=re.I).strip()  # corta a data do ato
        v.titulo = f"{rotulo[0].upper()}{rotulo[1:]} — {v.instituicao} ({ref})"[:200]
    return v


def filtrar(vagas: list[Vaga], user: dict) -> list[Vaga]:
    classes_ok = {CLASSE_FILTRO[i] for i in user.get("instituicoes", []) if i in CLASSE_FILTRO}
    # institutos, agências e "verificar manualmente" sempre passam — melhor sobrar que faltar
    classes_ok |= {"instituto público", "instituto privado", "agência/fundação", "verificar manualmente"}
    # O estado NÃO filtra aqui, de propósito. Filtrar na coleta é irreversível:
    # a vaga descartada não entra no banco e nenhum filtro do painel a traz de
    # volta. Com `estados: [SP, RJ, MG]` no config, o robô vinha jogando fora
    # todo concurso do resto do país cujo estado ele conseguia identificar — daí
    # o painel não achar vaga que aparece numa busca no Google. Quem quiser
    # recortar por UF faz isso no filtro do painel, que é reversível.
    saida = []
    for v in vagas:
        # a natureza fica de fora do teste: ela é derivada do mesmo texto, então usá-la
        # como prova de cargo faz a classificação confirmar o próprio erro
        if not clf.eh_vaga_academica(f"{v.titulo} {v.trecho_comprovacao}",
                                     v.classificacao_instituicao, v.fonte):
            continue
        if v.classificacao_instituicao not in classes_ok:
            continue
        if not user.get("incluir_vencidas", False) and v.status == "vencida":
            continue
        saida.append(_enriquecer(v))
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


def _avisar_assinantes(novas: list[Vaga], cfg: dict, user: dict) -> None:
    """Envia a cada assinante do dashboard só as vagas novas da área dele."""
    try:
        inscritos = assinaturas.carregar()
    except Exception as e:
        log.warning("não consegui ler assinaturas: %s", e)
        return
    if not inscritos:
        return
    cfg_email = cfg.get("alertas", {}).get("email", {})
    enviados = 0
    for pessoa in inscritos:
        minhas = assinaturas.vagas_do_assinante(pessoa, novas)
        if not minhas:
            continue
        corpo = montar_alerta(minhas, {"areas": pessoa.get("areas", [])})
        corpo += ("\n\n---\nVocê recebe este e-mail porque ativou o alerta em "
                  "https://vagas-academicas.streamlit.app — desative por lá quando quiser.")
        if email_alert.enviar(corpo, cfg_email, destinatario=pessoa["email"],
                              assunto=f"{len(minhas)} nova(s) vaga(s) acadêmica(s)"):
            enviados += 1
    log.info("alertas por e-mail enviados a %d assinante(s)", enviados)


def _buscar_palavra(palavra: str, cfg: dict, modo: str = "geral") -> int:
    """Busca ao vivo por uma palavra/área e salva no banco.
    modo 'geral': privadas (Gupy) + diários municipais (rápido).
    modo 'diarios': DOU (navegador, lento) + diários municipais."""
    dias = max(cfg["busca"].get("dias_retroativos", 30), 90)  # janela ampla p/ área específica
    vagas = []
    # O DOU entra nos dois modos. Antes só o modo 'diarios' o consultava, e como
    # "Busca geral" é o botão principal do painel, quem procurava uma área
    # específica não chegava à fonte onde sai a maior parte dos concursos
    # públicos — buscava só nas privadas e voltava achando que não havia vaga.
    vagas += dou.buscar_palavra(palavra, dias)
    if modo != "diarios":
        vagas += gupy.buscar([palavra])
    qd = querido_diario.buscar([palavra], dias, 100)
    for v in qd:
        v.area = palavra
    vagas += qd
    vagas = [v for v in vagas if clf.eh_vaga_academica(
        f"{v.titulo} {v.trecho_comprovacao}", v.classificacao_instituicao, v.fonte)]
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
    ap.add_argument("--email-teste", action="store_true",
                    help="envia 1 e-mail de teste (valida SMTP_USER/SMTP_PASS) e sai")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    if args.email_teste:
        ok = email_alert.enviar(
            "Teste de configuração do robô de vagas acadêmicas.\n\n"
            "Se você recebeu este e-mail, o envio de alertas está funcionando. 🎓",
            cfg.get("alertas", {}).get("email", {}),
            assunto="✅ Teste — Vagas Acadêmicas")
        print("e-mail de teste:", "ENVIADO" if ok else "FALHOU (confira SMTP_USER/SMTP_PASS)")
        return 0 if ok else 1

    # agenda.yaml (editável pelo dashboard) sobrepõe áreas e período
    agenda = Path(args.config).with_name("agenda.yaml")
    if agenda.exists():
        ag = yaml.safe_load(agenda.read_text(encoding="utf-8")) or {}
        if ag.get("areas"):
            cfg["usuario"]["areas"] = ag["areas"]
        if ag.get("dias_retroativos"):
            cfg["busca"]["dias_retroativos"] = ag["dias_retroativos"]

    if args.palavra:
        return _buscar_palavra(args.palavra, cfg, args.modo)

    user, busca, fontes = cfg["usuario"], cfg["busca"], cfg["fontes"]
    # base (professor, docente, concurso...) + as áreas escolhidas pelo usuário.
    # Os termos base sozinhos só acham o que usa essas palavras genéricas; é a
    # área que faz o robô procurar "epidemiologia" ou "economia" no DOU.
    termos = cfg.get("termos_base", []) + [a for a in user.get("areas", [])]
    dias = busca.get("dias_retroativos", 30)
    max_f = busca.get("max_resultados_por_fonte", 100)

    todas_vagas, falhas = [], []
    execucoes = [
        ("dou", lambda: dou.buscar(termos, dias, max_f)),
        # DOU oficial em XML: cobre as 3 seções e o dia inteiro, que é o que a
        # busca raspada acima não alcança. Sem INLABS_EMAIL/INLABS_SENHA no
        # ambiente, devolve vazio sem reclamar.
        ("inlabs", lambda: inlabs.buscar(dias, max_f)),
        # sem recorte de UF: diário municipal de qualquer estado interessa, e o
        # painel filtra depois quem quiser só um estado
        ("querido_diario", lambda: querido_diario.buscar(termos, dias, max_f)),
        # Diários Oficiais estaduais: São Paulo, Rio, Minas
        ("doe_sp", lambda: doe_sp.buscar(termos, dias, max_f)),
        ("doe_rj", lambda: doe_rj.buscar(termos, dias, max_f)),
        ("doe_mg", lambda: doe_mg.buscar(termos, dias, max_f)),
        # Diários Oficiais outros estados: PA, SC, RS, GO, ES
        ("doe_outros_estados", lambda: doe_outros_estados.buscar(termos, dias, max_f)),
        ("fapesp", lambda: fapesp.buscar(user.get("areas", []), max_f)),
        ("universidades_publicas", lambda: universidades_publicas.buscar(cfg.get("paginas_concursos", []), max_f)),
        ("universidades_privadas", lambda: universidades_privadas.buscar(cfg.get("paginas_privadas", []), max_f)),
        ("busca_aberta", lambda: busca_aberta.buscar(cfg.get("termos_base", []), user.get("areas", []), 50)),
        ("gupy", lambda: gupy.buscar(user.get("areas", []), max_f)),
        ("vagas_com", lambda: vagas_com.buscar(max_f)),
        # ANPOF publica poucos itens por mês e é a melhor fonte de filosofia, então
        # ganha janela própria de um ano. Concurso público tem tramitação longa: o
        # edital de dezembro com inscrição em janeiro caía fora dos 180 dias
        # antigos e nunca era coletado, mesmo o painel oferecendo filtro de 1 ano.
        # Custa uma página só — a listagem inteira vem numa requisição.
        ("anpof", lambda: anpof.buscar(max(dias, 365), max_f)),
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
        _avisar_assinantes(novas, cfg, user)

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

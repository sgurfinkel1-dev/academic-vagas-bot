"""Dashboard com filtros. Rodar: streamlit run dashboard.py"""
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from src import nuvem

RAIZ = Path(__file__).parent
DB = RAIZ / "data" / "processed" / "vagas.db"
AGENDA = RAIZ / "agenda.yaml"

st.set_page_config(page_title="Vagas Acadêmicas", layout="wide")


def _secret(chave, default=None):
    try:
        return st.secrets.get(chave, default)
    except Exception:
        return default


def _exigir_login():
    """Login Google — ativo só quando 'auth' está configurado nos secrets (nuvem)."""
    if not _secret("auth"):
        return  # local: acesso aberto
    if not getattr(st.user, "is_logged_in", False):
        st.title("🎓 Vagas Acadêmicas")
        st.info("Acesso restrito. Entre com sua conta Google para continuar.")
        st.button("Entrar com Google", on_click=st.login, type="primary")
        st.stop()
    with st.sidebar:
        st.caption(f"👤 {getattr(st.user, 'email', '')}")
        st.button("Sair", on_click=st.logout)


_exigir_login()

CLASSES = ["pública federal", "pública estadual", "pública municipal",
           "instituto público", "privada", "agência/fundação", "verificar manualmente"]
UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
       "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
# rótulo do filtro -> regex aplicada em natureza + título
TIPOS_VAGA = {
    "Professor efetivo (universidade pública)": r"efetivo|concurso",
    "Professor substituto": r"substituto|temporário|simplificado",
    "Professor visitante": r"visitante",
    "Professor colaborador": r"colaborador",
    "Pesquisador": r"pesquisador|research",
    "Pós-doutorado": r"pós.doutor|postdoc",
    "Bolsa": r"bolsa|bolsista|fellowship",
}

st.title("🎓 Vagas de Professor e Pesquisador — Brasil")

if not DB.exists():
    st.warning("Banco vazio. Clique em 'Buscar novas vagas' na barra lateral ou rode `python -m src.main`.")

def _busca_viva(palavra: str, modo: str, aviso: str):
    with st.spinner(aviso):
        r = subprocess.run([sys.executable, "-m", "src.main", "--palavra", palavra, "--modo", modo],
                           cwd=RAIZ, capture_output=True, text=True)
    st.success(r.stdout.strip()[-200:] if r.returncode == 0 else f"Erro: {r.stderr[-300:]}")
    st.rerun()


def _painel_config():
    """Configura áreas + período da busca automática; salva na agenda e, na nuvem, dispara o robô."""
    ag = yaml.safe_load(AGENDA.read_text(encoding="utf-8")) if AGENDA.exists() else {}
    repo, token = _secret("github_repo"), _secret("github_token")
    with st.sidebar.expander("⚙️ Busca automática", expanded=False):
        areas_txt = st.text_area("Áreas de interesse (uma por linha)",
                                 "\n".join(ag.get("areas", [])), height=110)
        dias = st.select_slider("Período (dias para trás)", [7, 15, 30, 60, 90],
                                value=ag.get("dias_retroativos", 30))
        if st.button("💾 Salvar configuração", use_container_width=True):
            nova = {"areas": [a.strip() for a in areas_txt.splitlines() if a.strip()],
                    "dias_retroativos": dias}
            conteudo = yaml.safe_dump(nova, allow_unicode=True, sort_keys=False)
            AGENDA.write_text(conteudo, encoding="utf-8")
            if repo and token:  # nuvem: persiste no repo p/ a busca agendada usar
                nuvem.commitar_arquivo(repo, "agenda.yaml", conteudo, token,
                                       "dashboard: atualiza agenda de busca")
            st.success("Configuração salva.")
        if repo and token:
            st.caption("A busca roda sozinha todo dia no horário agendado (GitHub Actions).")
            if st.button("☁️ Rodar busca completa agora", use_container_width=True):
                ok = nuvem.disparar_busca(repo, token)
                st.success("Disparado! Resultados chegam em alguns minutos.") if ok \
                    else st.error("Falha ao disparar — confira o token nos secrets.")
        else:
            st.caption("Modo local: use os botões de busca abaixo. "
                       "Na nuvem, aqui aparece o disparo automático.")


with st.sidebar:
    _painel_config()
    st.header("Filtros")
    f_classe = st.selectbox("Tipo de instituição", ["Todas"] + CLASSES)
    f_tipos = st.multiselect("Tipo de vaga (vazio = todos)", list(TIPOS_VAGA))
    f_estado = st.selectbox("Estado", ["Todos"] + UFS)
    f_status = st.selectbox("Status", ["Todos", "aberta", "sem prazo identificado", "vencida"])
    f_periodo = st.selectbox("Publicadas nos últimos",
                             ["Qualquer data", "7 dias", "15 dias", "30 dias", "90 dias"])
    f_titulacao = st.selectbox("Titulação exigida", ["Todas", "graduação", "mestrado",
                                                     "doutorado", "pós-doutorado", "livre-docência", "não informado"])
    with st.form("busca_texto", border=False):
        f_texto = st.text_input("Buscar por área/palavra (ex.: Direito, IA)")
        b_geral = st.form_submit_button("🔍 Busca geral", use_container_width=True)
        b_diarios = st.form_submit_button("📜 Buscar só nos diários oficiais", use_container_width=True)
    if b_geral and f_texto.strip():
        _busca_viva(f_texto.strip(), "geral",
                    f"Buscando '{f_texto}' em privadas (Gupy) e diários municipais... (~30 s)")
    if b_diarios and f_texto.strip():
        _busca_viva(f_texto.strip(), "diarios",
                    f"Buscando '{f_texto}' no DOU e diários municipais... (~2 min)")

if not DB.exists():
    st.stop()

df = pd.read_sql("SELECT * FROM vagas", sqlite3.connect(DB))

if f_classe != "Todas":
    df = df[df.classificacao_instituicao == f_classe]
if f_tipos:
    padrao = "|".join(TIPOS_VAGA[t] for t in f_tipos)
    df = df[(df.natureza + " " + df.titulo).str.contains(padrao, case=False, na=False)]
if f_estado != "Todos":
    df = df[df.estado == f_estado]
if f_status != "Todos":
    df = df[df.status == f_status]
if f_periodo != "Qualquer data":
    dias = {"7 dias": 7, "15 dias": 15, "30 dias": 30, "90 dias": 90}[f_periodo]
    corte = pd.Timestamp.now().normalize() - pd.Timedelta(days=dias)
    pub = pd.to_datetime(df.data_publicacao, format="%d/%m/%Y", errors="coerce")
    # mantém sem-data (listagens ao vivo de páginas/FAPESP, inerentemente atuais)
    df = df[pub.isna() | (pub >= corte)]
if f_titulacao != "Todas":
    df = df[df.titulacao_exigida == f_titulacao]
def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


if f_texto:
    import re
    cols = ["titulo", "area", "instituicao", "natureza", "trecho_comprovacao", "fonte"]
    alvo = df[cols].fillna("").agg(" ".join, axis=1).map(_sem_acento)
    padrao = r"\b" + re.escape(_sem_acento(f_texto.strip())) + r"\b"  # palavra inteira
    df = df[alvo.str.contains(padrao, na=False, regex=True)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vagas", len(df))
c2.metric("Abertas", int((df.status == "aberta").sum()))
c3.metric("Públicas", int(df.classificacao_instituicao.str.startswith("pública").sum()))
c4.metric("Bolsas/agências", int((df.classificacao_instituicao == "agência/fundação").sum()))

st.dataframe(
    df[["titulo", "instituicao", "classificacao_instituicao", "natureza",
        "estado", "titulacao_exigida", "prazo_inscricao", "status", "link_oficial"]],
    width="stretch", hide_index=True,
    column_config={
        "titulo": "Vaga", "instituicao": "Instituição",
        "classificacao_instituicao": "Tipo de instituição", "natureza": "Tipo de vaga",
        "estado": "UF", "titulacao_exigida": "Titulação",
        "prazo_inscricao": "Prazo", "status": "Status",
        "link_oficial": st.column_config.LinkColumn("Fonte", display_text="🔗 Abrir fonte"),
    },
)

st.subheader("Detalhes das vagas filtradas")
for _, r in df.head(50).iterrows():
    with st.container(border=True):
        st.markdown(f"**{r.titulo}**")
        st.caption(f"{r.instituicao} · {r.classificacao_instituicao} · {r.natureza}"
                   f" · prazo: {r.prazo_inscricao or 'ver edital'} · fonte: {r.fonte}")
        if r.trecho_comprovacao:
            st.caption(f"“{r.trecho_comprovacao}”")
        st.link_button("🔗 Acessar a fonte", r.link_oficial or "about:blank")
if len(df) > 50:
    st.caption(f"Mostrando detalhes das 50 primeiras de {len(df)} vagas — use os filtros para refinar.")

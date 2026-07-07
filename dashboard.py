"""Dashboard com filtros. Rodar: streamlit run dashboard.py"""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB = Path(__file__).parent / "data" / "processed" / "vagas.db"

st.set_page_config(page_title="Vagas Acadêmicas", layout="wide")
st.title("🎓 Vagas de Professor e Pesquisador — Brasil")

if not DB.exists():
    st.warning("Banco vazio. Rode primeiro: `python -m src.main`")
    st.stop()

df = pd.read_sql("SELECT * FROM vagas", sqlite3.connect(DB))

with st.sidebar:
    st.header("Filtros")
    f_classe = st.multiselect("Tipo de instituição", sorted(df.classificacao_instituicao.unique()))
    f_natureza = st.multiselect("Tipo de vaga", sorted(df.natureza.unique()))
    f_estado = st.multiselect("Estado", sorted(x for x in df.estado.unique() if x))
    f_status = st.multiselect("Status", sorted(df.status.unique()), default=["aberta"] if "aberta" in set(df.status) else [])
    f_titulacao = st.multiselect("Titulação exigida", sorted(df.titulacao_exigida.unique()))
    f_conf = st.multiselect("Confiança", sorted(df.confianca.unique()))
    f_texto = st.text_input("Buscar no título/área (ex.: Direito, IA)")

if f_classe:
    df = df[df.classificacao_instituicao.isin(f_classe)]
if f_natureza:
    df = df[df.natureza.isin(f_natureza)]
if f_estado:
    df = df[df.estado.isin(f_estado)]
if f_status:
    df = df[df.status.isin(f_status)]
if f_titulacao:
    df = df[df.titulacao_exigida.isin(f_titulacao)]
if f_conf:
    df = df[df.confianca.isin(f_conf)]
if f_texto:
    mask = df.titulo.str.contains(f_texto, case=False, na=False) | df.area.str.contains(f_texto, case=False, na=False)
    df = df[mask]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vagas", len(df))
c2.metric("Abertas", int((df.status == "aberta").sum()))
c3.metric("Públicas", int(df.classificacao_instituicao.str.startswith("pública").sum()))
c4.metric("Bolsas/agências", int((df.classificacao_instituicao == "agência/fundação").sum()))

st.dataframe(
    df[["titulo", "instituicao", "classificacao_instituicao", "natureza", "area",
        "estado", "titulacao_exigida", "prazo_inscricao", "status", "confianca", "link_oficial"]],
    use_container_width=True, hide_index=True,
    column_config={"link_oficial": st.column_config.LinkColumn("Link")},
)

with st.expander("Detalhe / trecho de comprovação"):
    for _, r in df.head(50).iterrows():
        st.markdown(f"**{r.titulo}** — {r.instituicao} · fonte: {r.fonte}")
        st.caption(r.trecho_comprovacao or "sem trecho")

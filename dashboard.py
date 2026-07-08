"""Dashboard com filtros. Rodar: streamlit run dashboard.py"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).parent
DB = RAIZ / "data" / "processed" / "vagas.db"

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

st.set_page_config(page_title="Vagas Acadêmicas", layout="wide")
st.title("🎓 Vagas de Professor e Pesquisador — Brasil")

if not DB.exists():
    st.warning("Banco vazio. Clique em 'Buscar novas vagas' na barra lateral ou rode `python -m src.main`.")

with st.sidebar:
    if st.button("🔄 Buscar novas vagas agora", use_container_width=True):
        with st.spinner("Consultando DOU, diários, FAPESP e universidades... (alguns minutos)"):
            r = subprocess.run([sys.executable, "-m", "src.main"], cwd=RAIZ,
                               capture_output=True, text=True)
        st.success("Busca concluída!" if r.returncode == 0 else f"Erro na busca: {r.stderr[-300:]}")
        st.rerun()

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
        st.form_submit_button("🔍 Filtrar resultados já baixados", use_container_width=True)
        buscar_ao_vivo = st.form_submit_button("🌐 Buscar essa área no DOU agora",
                                               use_container_width=True)
    if buscar_ao_vivo and f_texto.strip():
        with st.spinner(f"Buscando '{f_texto}' no Diário Oficial... (~2 min)"):
            r = subprocess.run([sys.executable, "-m", "src.main", "--palavra", f_texto.strip()],
                               cwd=RAIZ, capture_output=True, text=True)
        st.success(r.stdout.strip() or "Concluído." if r.returncode == 0 else f"Erro: {r.stderr[-300:]}")
        st.rerun()

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
if f_texto:
    cols = ["titulo", "area", "instituicao", "natureza", "trecho_comprovacao", "fonte"]
    alvo = df[cols].fillna("").agg(" ".join, axis=1)
    df = df[alvo.str.contains(f_texto, case=False, na=False)]

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

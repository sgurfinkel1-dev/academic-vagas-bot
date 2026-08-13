"""Dashboard com filtros. Rodar: streamlit run dashboard.py"""
import re
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml

from src import nuvem, assinaturas, sinonimos

RAIZ = Path(__file__).parent
DB = RAIZ / "data" / "processed" / "vagas.db"
AGENDA = RAIZ / "agenda.yaml"
ACESSO = RAIZ / "acesso.yaml"

st.set_page_config(page_title="Vagas Acadêmicas", layout="wide")

st.markdown("""
<style>
/* @import só vale como primeira regra da folha de estilo — abaixo de qualquer
   seletor o navegador o descarta e a fonte nunca chega a baixar. Mantenha esta
   linha no topo do bloco. */
@import url('https://fonts.googleapis.com/css2?family=Fira+Sans:wght@300;400;500;600;700&display=swap');

/* O badge do Streamlit Cloud mostra o perfil (e o e-mail) do dono do app para
   qualquer visitante. O toolbarMode do config.toml some com a barra de cima;
   isto cobre o badge do canto e o rodapé.

   O Community Cloud injeta esse badge fora do app, com classes geradas por
   hash que mudam a cada release — foi por isso que só [class*="viewerBadge"]
   parou de pegar o selo novo (o do avatar do criador). Mira-se então também o
   destino do link, que não muda de release para release. O app não renderiza
   nenhum link para streamlit.io, então a regra não alcança conteúdo próprio. */
[class*="viewerBadge"],
[class*="profileContainer"],
[data-testid*="viewerBadge" i],
[data-testid="stAppCreatorBadge"],
a[href*="share.streamlit.io"],
a[href*="streamlit.io/cloud"],
a[href^="https://streamlit.io/"],
[data-testid="stToolbar"], #MainMenu, footer { display: none !important; }

/* A troca de fonte não pode alcançar os ícones: o Streamlit os desenha como
   ligadura da Material Symbols (<span>keyboard_arrow_right</span>). Com outra
   família a ligadura não forma e o span, de 16px, mostra o nome cru por cima
   do rótulo — era a sobreposição vista nos expansores no celular. */
html, body, [class*="st-"]:not([data-testid^="stIconMaterial"]), button, input, textarea {
  font-family: 'Fira Sans', system-ui, sans-serif;
}
[data-testid^="stIconMaterial"] {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
}

/* Cartão de vaga: destaque na linha sob o cursor, como manda painel de dados. */
[data-testid="stVerticalBlockBorderWrapper"] {
  transition: border-color 200ms ease, box-shadow 200ms ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
  border-color: #0EA5E9;
  box-shadow: 0 1px 8px rgba(3, 105, 161, 0.10);
}

/* No celular as 4 métricas viram 4 telas empilhadas. Mantém em linha, menores. */
@media (max-width: 640px) {
  [data-testid="stMetric"] { padding: 0.25rem 0.4rem; }
  [data-testid="stMetricValue"] { font-size: 1.35rem; }
  [data-testid="stMetricLabel"] p { font-size: 0.7rem; }
  [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.25rem; }
  [data-testid="stHorizontalBlock"] > div { min-width: 0 !important; }
  h1 { font-size: 1.55rem !important; line-height: 1.25 !important; }
}

/* Alvo de toque mínimo de 44px (WCAG 2.5.5). Estava preso a max-width:640px, o
   que deixava tablet de fora: em 768px os botões mediam 38-40px. Vale por tipo
   de ponteiro, não por largura — quem toca com o dedo precisa do alvo maior
   independente do tamanho da tela. Os testids do Streamlit mudam de versão;
   estes são os controles que o usuário realmente toca — a barrinha de
   ferramentas de elemento fica de fora de propósito. */
@media (max-width: 1024px), (pointer: coarse) {
  [data-testid^="stBaseButton-"]:not([data-testid*="elementToolbar"]),
  [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
  .stLinkButton a { min-height: 44px; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}
</style>
""", unsafe_allow_html=True)


def _secret(chave, default=None):
    try:
        return st.secrets.get(chave, default)
    except Exception:
        return default


def _emails_permitidos() -> set:
    """Lista de e-mails autorizados (acesso.yaml). Vazio/ausente = qualquer conta Google entra."""
    if not ACESSO.exists():
        return set()
    dados = yaml.safe_load(ACESSO.read_text(encoding="utf-8")) or {}
    return {e.strip().lower() for e in dados.get("emails", []) if e.strip()}


def _exigir_login():
    """Login Google — ativo só quando 'auth' está configurado nos secrets (nuvem).
    Se acesso.yaml listar e-mails, só eles passam (os demais veem 'não autorizado')."""
    if not _secret("auth"):
        return  # local: acesso aberto
    if not getattr(st.user, "is_logged_in", False):
        st.title("🎓 Vagas Acadêmicas")
        st.info("Acesso restrito. Entre com sua conta Google para continuar.")
        st.button("Entrar com Google", on_click=st.login, type="primary")
        st.stop()
    email = (getattr(st.user, "email", "") or "").lower()
    permitidos = _emails_permitidos()
    if permitidos and email not in permitidos:
        st.title("🎓 Vagas Acadêmicas")
        st.error(f"A conta **{email}** não tem acesso a este painel. "
                 "Fale com quem administra o app para ser incluído.")
        st.button("Sair", on_click=st.logout)
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
# rótulo -> dias. Concurso público tem tramitação longa; edital de seis meses
# atrás ainda pode estar com inscrição aberta.
PERIODOS = {"Qualquer data": None, "7 dias": 7, "15 dias": 15, "30 dias": 30,
            "90 dias": 90, "6 meses": 180, "1 ano": 365}

st.title("🎓 Vagas de Professor e Pesquisador — Brasil")

if not DB.exists():
    st.warning("Banco vazio. Clique em 'Buscar novas vagas' na barra lateral ou rode `python -m src.main`.")

def _tem_busca_viva() -> bool:
    """Na nuvem, precisa dos secrets do GitHub (o robô roda lá, que tem navegador para o
    DOU; o container do Streamlit não tem). Local, roda direto. Sem isso, os botões de
    busca ao vivo nem aparecem — botão que não faz nada só confunde."""
    if _secret("github_repo") and _secret("github_token"):
        return True
    return RAIZ.joinpath("src").exists() and not _secret("auth")


def _busca_viva(palavra: str, modo: str, aviso: str):
    """Dispara o robô no GitHub Actions (nuvem) ou direto (local)."""
    repo, token = _secret("github_repo"), _secret("github_token")
    if repo and token:
        if nuvem.disparar_busca(repo, token, palavra=palavra, modo=modo):
            st.success(f"🔎 Busca por '{palavra}' iniciada na nuvem. "
                       "Os resultados entram no painel em ~5-10 min (a página se atualiza sozinha).")
        else:
            st.error("Não consegui iniciar a busca. Avise o responsável pelo app.")
        return
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
        dias = st.select_slider("Período (dias para trás)",
                                [7, 15, 30, 60, 90, 180, 365],
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
    _painel_alerta_email(repo, token)


def _painel_alerta_email(repo, token):
    """Cada pessoa ativa o próprio alerta: recebe por e-mail as vagas novas da sua área."""
    meu_email = getattr(st.user, "email", "") or ""
    inscritos = assinaturas.carregar()
    atual = next((a for a in inscritos if a.get("email", "").lower() == meu_email.lower()), None)
    with st.sidebar.expander("📧 Receber vagas por e-mail", expanded=False):
        if not meu_email:
            st.caption("Entre com sua conta Google para ativar o alerta.")
            return
        st.caption(f"Enviaremos para **{meu_email}** quando surgirem vagas novas.")
        ativo = st.checkbox("Quero receber alertas por e-mail", value=atual is not None)
        areas_txt = st.text_area(
            "Minhas áreas (uma por linha; vazio = todas as vagas)",
            "\n".join(atual.get("areas", [])) if atual else "", height=90,
            key="areas_alerta")
        if st.button("💾 Salvar meu alerta", use_container_width=True):
            try:
                novos = assinaturas.upsert(inscritos, meu_email,
                                           areas_txt.splitlines(), ativo=ativo)
            except ValueError as e:
                st.error(str(e))
                return
            conteudo = assinaturas.serializar(novos)
            if repo and token:
                ok = nuvem.commitar_arquivo(repo, "assinaturas.yaml", conteudo, token,
                                            "dashboard: atualiza assinaturas de alerta")
                if not ok:
                    st.error("Não consegui salvar sua inscrição. Avise o responsável pelo app.")
                    return
            else:
                assinaturas.ARQUIVO.write_text(conteudo, encoding="utf-8")
            st.success("Alerta ativado! Você receberá as vagas novas da sua área."
                       if ativo else "Alerta desativado.")


with st.sidebar:
    _painel_config()

# A busca é a ação principal e fica sempre visível — filtro escondido atrás de
# menu é o anti-padrão clássico deste tipo de painel, e na sidebar do celular
# ele simplesmente desaparece.
with st.form("busca_texto", border=False):
    f_texto = st.text_input("Buscar por área ou palavra",
                            placeholder="Ex.: Direito, Filosofia, Inteligência Artificial")
    ao_vivo = _tem_busca_viva()
    bc1, bc2 = st.columns(2)
    b_geral = bc1.form_submit_button("Busca geral", use_container_width=True,
                                     type="primary")
    b_diarios = bc2.form_submit_button("Só nos diários oficiais",
                                       use_container_width=True)

with st.expander("Filtros avançados", expanded=False):
    fc1, fc2, fc3 = st.columns(3)
    f_classe = fc1.selectbox("Tipo de instituição", ["Todas"] + CLASSES)
    f_estado = fc2.selectbox("Estado", ["Todos"] + UFS)
    f_status = fc3.selectbox("Status", ["Todos", "aberta", "sem prazo identificado", "vencida"])

    fc4, fc5 = st.columns(2)
    f_periodo = fc4.selectbox("Publicadas nos últimos", list(PERIODOS))
    f_titulacao = fc5.selectbox("Titulação exigida", ["Todas", "graduação", "mestrado",
                                                      "doutorado", "pós-doutorado",
                                                      "livre-docência", "não informado"])
    f_tipos = st.multiselect("Tipo de vaga (vazio = todos)", list(TIPOS_VAGA))

if ao_vivo and b_geral and f_texto.strip():
    _busca_viva(f_texto.strip(), "geral",
                f"Buscando '{f_texto}' no DOU, em privadas (Gupy) e diários... (~2 min)")
if ao_vivo and b_diarios and f_texto.strip():
    _busca_viva(f_texto.strip(), "diarios",
                f"Buscando '{f_texto}' no DOU, nos diários estaduais "
                "(SP, MG, PR, RS, SC) e nos municipais... (~3 min)")

if not DB.exists():
    st.stop()

with sqlite3.connect(DB) as _con:
    df = pd.read_sql("SELECT * FROM vagas", _con)


def _status_atual(prazo: str, gravado: str) -> str:
    """O status vem gravado da coleta e envelhece no banco: vaga recolhida com
    prazo futuro continua marcada 'aberta' depois que o prazo passa. Recalcula
    na leitura — quem abre o painel quer saber se dá para se inscrever hoje."""
    p = (prazo or "").strip()
    if not p:
        return gravado or "sem prazo identificado"
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return "aberta" if datetime.strptime(p, fmt).date() >= date.today() else "vencida"
        except ValueError:
            continue
    return gravado or "sem prazo identificado"


df["status"] = [_status_atual(p, s) for p, s in zip(df.prazo_inscricao, df.status)]

if f_classe != "Todas":
    df = df[df.classificacao_instituicao == f_classe]
if f_tipos:
    padrao = "|".join(TIPOS_VAGA[t] for t in f_tipos)
    df = df[(df.natureza + " " + df.titulo).str.contains(padrao, case=False, na=False)]
if f_estado != "Todos":
    df = df[df.estado == f_estado]
if f_status != "Todos":
    df = df[df.status == f_status]
if PERIODOS[f_periodo] is not None:
    corte = pd.Timestamp.now().normalize() - pd.Timedelta(days=PERIODOS[f_periodo])
    # As fontes não falam a mesma língua de data: a maioria grava DD/MM/AAAA, mas
    # parte vem em ISO (AAAA-MM-DD). Lendo só um formato, o outro virava NaT e
    # escapava do filtro como se fosse "sem data" — vaga antiga aparecendo em
    # "últimos 7 dias". Tenta os dois antes de desistir.
    pub = pd.to_datetime(df.data_publicacao, format="%d/%m/%Y", errors="coerce")
    faltando = pub.isna()
    if faltando.any():
        pub = pub.fillna(pd.to_datetime(df.data_publicacao.where(faltando),
                                        format="ISO8601", errors="coerce"))
    # mantém sem-data (listagens ao vivo de páginas/FAPESP, inerentemente atuais)
    df = df[pub.isna() | (pub >= corte)]
if f_titulacao != "Todas":
    df = df[df.titulacao_exigida == f_titulacao]
def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


if f_texto:
    # cada grupo é um termo: "epistemologia" também acha "teoria do conhecimento"
    grupos = sinonimos.expandir(f_texto)
    palavras = [g[0] for g in grupos]  # rótulo do grupo, só para exibir
    # três níveis: a subárea declarada no edital ("Subárea: Filosofia Política") é o
    # sinal mais forte; título/área vêm depois; o corpo do edital só desempata.
    subarea = df["subarea"].fillna("").map(_sem_acento)
    tema = df[["titulo", "area"]].fillna("").agg(" ".join, axis=1).map(_sem_acento)
    corpo = df[["instituicao", "natureza", "trecho_comprovacao"]].fillna("").agg(" ".join, axis=1).map(_sem_acento)

    def _casa(serie):
        return pd.concat([serie.str.contains(
            r"\b(?:" + "|".join(re.escape(f) for f in g) + r")\b", na=False)
            for g in grupos], axis=1, keys=palavras)

    n_sub, n_tema, n_corpo = _casa(subarea), _casa(tema), _casa(corpo)
    # termo raro vale mais que termo comum: em "filosofia da lógica" quase toda vaga
    # da lista casa "filosofia", então quem decide a ordem é "lógica".
    onde = n_sub | n_tema | n_corpo
    freq = onde.sum(axis=0).clip(lower=1)
    peso = np.log(len(df) / freq) + 0.1

    # cada termo conta UMA vez, pelo melhor campo em que aparece. Somar os campos
    # faria "filosofia" (em subárea + título) ganhar de "lógica", que é o termo raro.
    campo = np.maximum.reduce([n_sub.values * 4, n_tema.values * 3, n_corpo.values * 1])
    pontos = pd.Series((campo * peso.values).sum(axis=1), index=df.index)
    # bônus grande para quem casa TODOS os termos: é a interseção que se pediu
    completos = onde.all(axis=1)
    pontos = pontos + completos * peso.sum() * 4

    # Entra quem tem o termo em qualquer campo, inclusive só no corpo. Antes o
    # corpo não bastava, e isso escondia justamente o caso mais comum: edital do
    # DOU tem título genérico ("Professor efetivo — Universidade Federal do
    # Ceará") e a subárea aparece só no texto. Buscar "lógica" devolvia zero
    # tendo dois editais federais que a citam. Quem casa só no corpo vale menos
    # na pontuação (peso 1 contra 3 e 4) e por isso já aparece no fim da lista —
    # não precisa ser excluído, precisa ser ordenado.
    relevantes = (n_sub | n_tema | n_corpo).any(axis=1)
    df = df[relevantes].assign(_p=pontos[relevantes]) \
                       .sort_values("_p", ascending=False).drop(columns="_p")
    n_completos = int((completos & relevantes).sum())
    if len(df) and len(palavras) > 1:
        st.caption(f"{n_completos} vaga(s) com todos os termos de “{f_texto}” aparecem primeiro; "
                   f"depois as {len(df) - n_completos} que batem em parte." if n_completos
                   else f"Nenhuma vaga combina “{' + '.join(palavras)}” ao mesmo tempo. "
                        f"Mostrando {len(df)} por proximidade, as mais específicas primeiro.")
    if not len(df):
        st.info(f"Nenhuma vaga de “{f_texto}”.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vagas", len(df))
c2.metric("Abertas", int((df.status == "aberta").sum()))
c3.metric("Públicas", int(df.classificacao_instituicao.str.startswith("pública").sum()))
c4.metric("Bolsas/agências", int((df.classificacao_instituicao == "agência/fundação").sum()))

# A tabela tem muitas colunas p/ caber num celular: fica recolhida, e os cartões
# abaixo (que quebram linha bem em tela estreita) são a leitura principal.
# O link vem PRIMEIRO: como última coluna ele só aparecia depois de rolar a tabela
# até o fim, então na prática ninguém achava o caminho para a fonte.
with st.expander("📊 Ver como tabela", expanded=False):
    st.dataframe(
        df[["link_oficial", "titulo", "instituicao", "classificacao_instituicao",
            "natureza", "estado", "titulacao_exigida", "prazo_inscricao", "status"]],
        width="stretch", hide_index=True,
        column_config={
            "link_oficial": st.column_config.LinkColumn("Fonte", display_text="🔗 Abrir",
                                                        width="small"),
            "titulo": "Vaga", "instituicao": "Instituição",
            "classificacao_instituicao": "Tipo de instituição", "natureza": "Tipo de vaga",
            "estado": "UF", "titulacao_exigida": "Titulação",
            "prazo_inscricao": "Prazo", "status": "Status",
        },
    )

# h2: entre o h1 do topo e esta seção não há nível intermediário, e pular de h1
# para h3 quebra a navegação por títulos de quem usa leitor de tela.
st.header("Vagas encontradas")
# Status e prazo decidem se vale abrir o edital, então vêm em cor, no topo.
CORES_STATUS = {"aberta": "green", "vencida": "red", "sem prazo identificado": "orange"}
_MD_ESPECIAIS = re.compile(r"([\\`*_\[\]()<>#|~])")


def _md(valor) -> str:
    """Escapa markdown de texto vindo de scraping. O título e o trecho do edital
    são conteúdo de terceiros: sem escapar, um "[clique](http://...)" no título
    de um edital vira link de verdade dentro do cartão."""
    return _MD_ESPECIAIS.sub(r"\\\1", str(valor or ""))


def _link_seguro(url) -> str:
    """Só http(s) vira botão; qualquer outro esquema (javascript:, data:) sai."""
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


for _, r in df.head(50).iterrows():
    with st.container(border=True):
        cor = CORES_STATUS.get(r.status, "gray")
        prazo = _md(r.prazo_inscricao or "ver edital")
        st.markdown(f":{cor}-background[**{r.status}**] &nbsp; :gray[prazo: {prazo}]")
        st.markdown(f"**{_md(r.titulo)}**")
        st.caption(f"{_md(r.instituicao)} · {r.classificacao_instituicao} · {_md(r.natureza)}"
                   f" · {r.estado or '—'} · fonte: {_md(r.fonte)}")
        if r.trecho_comprovacao:
            st.caption(f"“{_md(r.trecho_comprovacao)}”")
        destino = _link_seguro(r.link_oficial)
        if destino:
            st.link_button("Acessar a fonte", destino)
        else:
            st.caption("Sem link oficial confiável para esta vaga.")
if len(df) > 50:
    st.caption(f"Mostrando detalhes das 50 primeiras de {len(df)} vagas — use os filtros para refinar.")


def _declarar_idioma():
    """Declara o idioma da página no <html>.

    O Streamlit fixa lang="en" e não expõe configuração para trocar. O painel é
    todo em português, e leitor de tela lia o texto com voz inglesa (WCAG
    3.1.1). Mexer no documento pai é o único caminho, então é o que se faz aqui.

    Nota sobre o selo do Community Cloud, para quem vier depois: houve neste
    mesmo script uma tentativa de removê-lo, mirando o destino do link e a
    posição na tela. Funcionou em laboratório e não no app publicado — ou o
    iframe não alcança o documento pai na nuvem, ou o selo vive em shadow DOM
    fechado. Foi retirada em vez de mantida sem efeito. O selo é injetado pelo
    host: quem quiser mesmo tirá-lo precisa sair do Community Cloud.
    """
    components.html(
        """
<script>
(function () {
  var doc;
  try { doc = window.parent.document; } catch (e) { return; }  // sem acesso: desiste
  if (!doc || !doc.documentElement) return;
  doc.documentElement.lang = 'pt-BR';
})();
</script>
        """,
        height=0,
    )


_declarar_idioma()

"""INLABS: o DOU oficial em XML, dia a dia, nas três seções.

Por que existe, se dou.py já consulta o DOU: a página de busca do in.gov.br
pagina por cursor Liferay e o robô lê só a primeira página — medido em
11/08/2026, 1 de 126 páginas para "professor". O INLABS entrega o dia inteiro
num ZIP: 6,1 MB e ~4,5 s para DO1+DO2+DO3, 3.339 artigos, sem raspagem e sem
parâmetro a adivinhar. A Seção 2, que a busca antiga nem olhava, rendeu 32 dos
63 editais docentes do dia.

Exige cadastro gratuito em https://inlabs.in.gov.br e as variáveis de ambiente
INLABS_EMAIL e INLABS_SENHA. Sem elas a fonte se declara desligada e devolve
lista vazia — nunca derruba a execução.
"""
import io
import logging
import os
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

BASE = "https://inlabs.in.gov.br"
SECOES = ("DO1", "DO2", "DO3")

# As duas âncoras têm de aparecer no mesmo artigo. "concurso público" sozinho é
# vaga de qualquer cargo; "professor" sozinho casa com nome de órgão — o DOU tem
# dezenas de "Hospital Universitário Professor Fulano" por dia.
CARGO = re.compile(r"professor|docente|magist[ée]rio|pesquisador|p[óo]s-doutor", re.I)
ATO = re.compile(r"concurso p[úu]blico|processo seletivo|sele[çc][ãa]o p[úu]blica|edital", re.I)
# O artType do XML separa vaga de burocracia melhor que qualquer regex no corpo:
# medido em 11-12/08/2026, casar só cargo+ato trazia 114 artigos, dos quais 46
# eram portaria de nomeação da Seção 2 e 12 extrato de contrato. Toda portaria
# cita o edital do concurso que nomeou — por isso o corpo não distingue.
TIPO_VAGA = re.compile(r"edital|concurso|processo seletivo|retifica", re.I)
TIPO_FORA = re.compile(r"licita|preg[ãa]o|concorr[êe]ncia|contrato|aditivo", re.I)
TAG = re.compile(r"<[^>]+>")


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", texto or "")).strip()


def _tentar(fn, tentativas: int = 4):
    """O DNS de inlabs.in.gov.br faz rodízio entre IPs e nem todos respondem na
    443 — medido em 12/08/2026: 170.246.254.40 engolia o SYN (timeout de 20s)
    enquanto 177.15.137.168 atendia em 1s. Cada tentativa resolve o nome de
    novo, então repetir cai noutro IP. Sem isto o sorteio ruim derruba a coleta
    do dia inteiro; httpx.HTTPTransport(retries=) não serve porque só cobre
    ConnectError, e o sintoma aqui é ConnectTimeout.
    """
    for i in range(tentativas):
        try:
            return fn()
        except httpx.TransportError:
            if i == tentativas - 1:
                raise
            log.debug("INLABS: rede falhou, tentativa %d/%d", i + 1, tentativas)


def _entrar() -> httpx.Client | None:
    email = os.getenv("INLABS_EMAIL") or os.getenv("INLABS_USER") or ""
    senha = os.getenv("INLABS_SENHA") or os.getenv("INLABS_PASS") or ""
    if not (email and senha):
        log.info("INLABS: INLABS_EMAIL/INLABS_SENHA ausentes — fonte pulada")
        return None
    cli = httpx.Client(base_url=BASE, follow_redirects=True,
                       timeout=httpx.Timeout(120, connect=8),
                       headers={"User-Agent": "academic-vagas-bot"})
    try:
        r = _tentar(lambda: cli.post("/logar.php", data={"email": email, "password": senha}))
    except httpx.TransportError as e:
        log.warning("INLABS: login falhou: %s", e)
        cli.close()
        return None
    # credencial errada devolve 302 de volta para acessar.php. Conferir a URL
    # final, e não o cookie: o site emite PHPSESSID logado ou não.
    if "acessar.php" in str(r.url):
        log.warning("INLABS: login recusado — confira INLABS_EMAIL/INLABS_SENHA")
        cli.close()
        return None
    return cli


def _artigos(conteudo: bytes):
    """Cada XML do ZIP traz um <article> com atributos e CDATA em Identifica/Texto."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile:
        return
    for nome in zf.namelist():
        if not nome.lower().endswith(".xml"):
            continue
        try:
            raiz = ET.fromstring(zf.read(nome).decode("utf-8", errors="replace").lstrip("﻿"))
        except ET.ParseError:
            continue
        art = raiz if raiz.tag == "article" else raiz.find("article")
        if art is not None:
            yield art


def _vaga(art, secao: str) -> Vaga | None:
    corpo = art.find("body")
    if corpo is None:
        return None
    titulo = _limpo((corpo.findtext("Identifica") or "").strip())
    texto = _limpo(corpo.findtext("Texto") or "")
    hierarquia = art.get("artCategory") or ""
    tipo = art.get("artType") or ""
    if TIPO_FORA.search(tipo) or not (TIPO_VAGA.search(tipo) or TIPO_VAGA.search(titulo)):
        return None
    tudo = f"{titulo} {texto} {hierarquia}"
    if not (CARGO.search(tudo) and ATO.search(tudo)):
        return None
    prazo = clf.extrair_prazo(tudo)
    return Vaga(
        titulo=(titulo or art.get("name") or "")[:200],
        instituicao=hierarquia.split("/")[-1].strip() or "ver edital",
        classificacao_instituicao=clf.classificar_instituicao(tudo),
        natureza=clf.classificar_natureza(tudo),
        estado=clf.extrair_estado(tudo),
        titulacao_exigida=clf.classificar_titulacao(tudo),
        data_publicacao=art.get("pubDate", ""),
        prazo_inscricao=prazo,
        status=clf.status_por_prazo(prazo),
        link_oficial=art.get("pdfPage", ""),
        fonte=f"DOU/INLABS ({secao})",
        trecho_comprovacao=texto[:600] or titulo,
        confianca="alto",
    )


def buscar(dias: int = 30, max_por_fonte: int = 200) -> list[Vaga]:
    cli = _entrar()
    if cli is None:
        return []
    vagas, baixados = [], 0
    try:
        for n in range(dias):
            dia = (date.today() - timedelta(days=n)).strftime("%Y-%m-%d")
            for secao in SECOES:
                try:
                    r = _tentar(lambda: cli.get(f"/index.php?p={dia}&dl={dia}-{secao}.zip"))
                except Exception as e:
                    log.warning("INLABS %s %s: %s", dia, secao, e)
                    continue
                # fim de semana e feriado não têm edição: o site devolve página,
                # não ZIP. Silêncio aqui é esperado, ao contrário de ZIP vazio.
                if r.status_code != 200 or r.content[:2] != b"PK":
                    continue
                baixados += 1
                for art in _artigos(r.content):
                    v = _vaga(art, secao)
                    if v:
                        vagas.append(v)
                    if len(vagas) >= max_por_fonte:
                        log.info("INLABS: teto de %d atingido em %s/%s (%d zips lidos)",
                                 max_por_fonte, dia, secao, baixados)
                        return vagas
    finally:
        cli.close()
    log.info("INLABS: %d zips lidos, %d vagas", baixados, len(vagas))
    return vagas

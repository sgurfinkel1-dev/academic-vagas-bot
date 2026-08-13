"""Diários Oficiais de outros estados: PA, SC, RS, GO, ES."""
import logging
import re
from datetime import date, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")

# Mapa de estados para URLs dos diários oficiais
DOESS = {
    "PA": {
        "nome": "Pará",
        "url": "https://www.diariooficialestadual.com.br",
        "busca_path": "/busca",
        "param": "q",
    },
    "SC": {
        "nome": "Santa Catarina",
        "url": "https://www.portaldatransparencia.gov.sc.gov.br",
        "busca_path": "/diarios-oficiais",
        "param": "search",
    },
    "RS": {
        "nome": "Rio Grande do Sul",
        "url": "https://www.diariooficial.rs.gov.br",
        "busca_path": "/buscar",
        "param": "q",
    },
    "GO": {
        "nome": "Goiás",
        "url": "https://diario.imprensaoficial.go.gov.br",
        "busca_path": "/busca",
        "param": "termo",
    },
    "ES": {
        "nome": "Espírito Santo",
        "url": "https://www.ionet.com.br",
        "busca_path": "/diario-oficial/busca",
        "param": "q",
    },
}


def buscar_estado(sigla: str, termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Busca em DOE genérico via scraping."""
    vagas = []
    if sigla not in DOESS:
        log.warning(f"DOE_{sigla}: estado não configurado")
        return vagas

    config = DOESS[sigla]
    desde = (date.today() - timedelta(days=dias)).isoformat()

    for termo in termos:
        try:
            url_busca = config["url"] + config["busca_path"]
            r = httpx.get(url_busca, params={
                config["param"]: termo,
                "data_inicio": desde,
            }, timeout=15)

            if r.status_code != 200:
                log.warning(f"DOE_{sigla}: busca '{termo}' retornou {r.status_code}")
                continue

            soup = BeautifulSoup(r.content, "html.parser")

            # Tenta encontrar qualquer elemento que pareça ser um resultado
            resultados = soup.find_all(
                class_=re.compile(r"resultado|item|diario|gazette|documento|edital", re.I)
            )
            # Fallback: procura por links que parecem diários
            if not resultados:
                resultados = soup.find_all("a", href=re.compile(r"diario|edital|concurso|vaga", re.I))

            count = 0
            for res in resultados:
                if count >= max_por_fonte:
                    break

                if isinstance(res, str):
                    continue

                # Extrai título e link
                if res.name == "a":
                    titulo = res.get_text(strip=True)
                    link = res.get("href", "")
                else:
                    link_elem = res.find("a")
                    if not link_elem:
                        continue
                    titulo = link_elem.get_text(strip=True)
                    link = link_elem.get("href", "")

                if not titulo or len(titulo) < 5:
                    continue

                # Filtro: só vagas
                if not any(
                    kw in titulo.lower()
                    for kw in ["professor", "docente", "concurso", "edital", "processo seletivo", "pesquisador", "vaga"]
                ):
                    continue

                # Evita portarias de nomeação
                if any(kw in titulo.lower() for kw in ["nomeação", "exoneração", "demissão"]):
                    continue

                # Monta URL completa se relativa
                if link and not link.startswith("http"):
                    link = config["url"] + "/" + link.lstrip("/")

                data_elem = res.find(class_=re.compile(r"data|date", re.I))
                data_pub = data_elem.get_text(strip=True) if data_elem else ""

                prazo = clf.extrair_prazo(titulo)
                vagas.append(
                    Vaga(
                        titulo=titulo[:200],
                        instituicao=f"{config['nome']} (DOE)",
                        classificacao_instituicao="pública estadual",
                        natureza=clf.classificar_natureza(titulo.lower()),
                        estado=sigla,
                        titulacao_exigida=clf.classificar_titulacao(titulo),
                        data_publicacao=data_pub,
                        prazo_inscricao=prazo,
                        status=clf.status_por_prazo(prazo),
                        link_oficial=link or config["url"],
                        fonte=f"DOE-{sigla} (busca: {termo})",
                        trecho_comprovacao=titulo[:600],
                        confianca="médio",
                    )
                )
                count += 1

        except Exception as e:
            log.warning(f"DOE_{sigla}: erro ao buscar '{termo}': {e}")
            continue

    return vagas


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Busca em todos os DOEs configurados (PA, SC, RS, GO, ES)."""
    todas = []
    for sigla in ["PA", "SC", "RS", "GO", "ES"]:
        todas.extend(buscar_estado(sigla, termos, dias, max_por_fonte))
    return todas

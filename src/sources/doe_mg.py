"""Diário Oficial do Estado de Minas Gerais (Imprensa Oficial)."""
import logging
import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
BASE = "https://www.imprensaoficial.mg.gov.br"

def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Busca no DOE-MG via scraping."""
    vagas = []
    desde = (date.today() - timedelta(days=dias)).isoformat()

    for termo in termos:
        try:
            # Busca na Imprensa Oficial MG
            r = httpx.get(f"{BASE}/buscar", params={
                "termo": termo,
                "data_ini": desde.replace("-", "/"),
                "data_fim": date.today().isoformat().replace("-", "/"),
            }, timeout=15)

            if r.status_code != 200:
                log.warning(f"DOE-MG: busca '{termo}' retornou {r.status_code}")
                continue

            soup = BeautifulSoup(r.content, "html.parser")

            # Tenta encontrar resultados (estrutura pode variar)
            resultados = soup.find_all(class_=re.compile(r"resultado|item|diario|gazette|documento"))
            if not resultados:
                # Fallback: procura por links que parecem ser diários
                resultados = soup.find_all("a", href=re.compile(r"/diario|/edital|/concurso"))

            count = 0
            for res in resultados:
                if count >= max_por_fonte:
                    break

                if isinstance(res, str):
                    continue

                # Se é link direto
                if res.name == "a":
                    titulo = res.get_text(strip=True)
                    link = res.get("href", "")
                else:
                    # Se é div/container
                    link_elem = res.find("a")
                    if not link_elem:
                        continue
                    titulo = link_elem.get_text(strip=True)
                    link = link_elem.get("href", "")

                # Filtro
                if not any(kw in titulo.lower() for kw in ["professor", "docente", "concurso", "edital", "processo seletivo", "pesquisador"]):
                    continue

                if "nomeação" in titulo.lower() or "exoneração" in titulo.lower():
                    continue

                # Monta URL completa se relativa
                if link and not link.startswith("http"):
                    link = BASE + "/" + link.lstrip("/")

                data_elem = res.find(class_=re.compile(r"data|date"))
                data_pub = data_elem.get_text(strip=True) if data_elem else ""

                prazo = clf.extrair_prazo(titulo)
                vagas.append(Vaga(
                    titulo=titulo[:200],
                    instituicao="Minas Gerais (DOE)",
                    classificacao_instituicao="pública estadual",
                    natureza=clf.classificar_natureza(titulo.lower()),
                    estado="MG",
                    titulacao_exigida=clf.classificar_titulacao(titulo),
                    data_publicacao=data_pub,
                    prazo_inscricao=prazo,
                    status=clf.status_por_prazo(prazo),
                    link_oficial=link or BASE,
                    fonte=f"DOE-MG (busca: {termo})",
                    trecho_comprovacao=titulo[:600],
                    confianca="médio",
                ))
                count += 1

        except Exception as e:
            log.warning(f"DOE-MG: erro ao buscar '{termo}': {e}")
            continue

    return vagas

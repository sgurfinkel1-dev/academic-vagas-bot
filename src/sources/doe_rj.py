"""Diário Oficial do Estado do Rio de Janeiro."""
import logging
import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
BASE = "https://www.govinfo.rj.gov.br/diariooficial"

def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Busca no DOE-RJ via scraping da página de busca."""
    vagas = []
    desde = (date.today() - timedelta(days=dias)).isoformat()

    for termo in termos:
        try:
            # Busca na página de diários do RJ
            r = httpx.get(f"{BASE}/busca", params={
                "query": termo,
                "inicio": desde,
            }, timeout=15)

            if r.status_code != 200:
                log.warning(f"DOE-RJ: busca '{termo}' retornou {r.status_code}")
                continue

            soup = BeautifulSoup(r.content, "html.parser")
            resultados = soup.find_all(class_=re.compile(r"resultado|diario|gazette"))

            count = 0
            for res in resultados:
                if count >= max_por_fonte:
                    break

                # Extrai título e link
                link_elem = res.find("a")
                if not link_elem:
                    continue

                titulo = link_elem.get_text(strip=True)
                link = link_elem.get("href", "")

                # Tenta baixar conteúdo do link se for relativo
                if link and not link.startswith("http"):
                    link = BASE + "/" + link.lstrip("/")

                # Filtro de keywords
                if not any(kw in titulo.lower() for kw in ["professor", "docente", "concurso", "edital", "processo seletivo", "pesquisador"]):
                    continue

                if "nomeação" in titulo.lower() or "exoneração" in titulo.lower():
                    continue

                # Tenta extrair data e conteúdo
                data_elem = res.find(class_=re.compile(r"data|date"))
                data_pub = data_elem.get_text(strip=True) if data_elem else ""

                texto_elem = res.find(class_=re.compile(r"resumo|excerpt|conteudo|content"))
                texto = texto_elem.get_text(strip=True) if texto_elem else titulo

                prazo = clf.extrair_prazo(texto)
                vagas.append(Vaga(
                    titulo=titulo[:200],
                    instituicao="Rio de Janeiro (DOE)",
                    classificacao_instituicao="pública estadual",
                    natureza=clf.classificar_natureza(f"{titulo} {texto}".lower()),
                    estado="RJ",
                    titulacao_exigida=clf.classificar_titulacao(f"{titulo} {texto}"),
                    data_publicacao=data_pub,
                    prazo_inscricao=prazo,
                    status=clf.status_por_prazo(prazo),
                    link_oficial=link or BASE,
                    fonte=f"DOE-RJ (busca: {termo})",
                    trecho_comprovacao=texto[:600],
                    confianca="médio",
                ))
                count += 1

        except Exception as e:
            log.warning(f"DOE-RJ: erro ao buscar '{termo}': {e}")
            continue

    return vagas

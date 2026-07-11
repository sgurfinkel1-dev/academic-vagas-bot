"""Vagas em instituições privadas via API pública do portal Gupy
(usada por Cogna/Anhanguera, Estácio, Ânima, Cruzeiro do Sul etc.)."""
import logging
import re

from ..extractors.html_extractor import baixar_json
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://employability-portal.gupy.io/api/v1/jobs"
TERMOS = ["professor ensino superior", "professor universitário", "docente", "professor"]
SUPERIOR = re.compile(r"ensino superior|universit|faculdade|docente|gradua|p[óo]s-gradua|lecturer", re.I)
UF = {"Acre": "AC", "Alagoas": "AL", "Amapá": "AP", "Amazonas": "AM", "Bahia": "BA", "Ceará": "CE",
      "Distrito Federal": "DF", "Espírito Santo": "ES", "Goiás": "GO", "Maranhão": "MA", "Mato Grosso": "MT",
      "Mato Grosso do Sul": "MS", "Minas Gerais": "MG", "Pará": "PA", "Paraíba": "PB", "Paraná": "PR",
      "Pernambuco": "PE", "Piauí": "PI", "Rio de Janeiro": "RJ", "Rio Grande do Norte": "RN",
      "Rio Grande do Sul": "RS", "Rondônia": "RO", "Roraima": "RR", "Santa Catarina": "SC",
      "São Paulo": "SP", "Sergipe": "SE", "Tocantins": "TO"}
MODALIDADE = {"on-site": "presencial", "remote": "remoto", "hybrid": "híbrido"}


def buscar(termos_extra: list[str] | None = None, max_por_fonte: int = 100) -> list[Vaga]:
    vagas, vistos = [], set()
    for termo in TERMOS + (termos_extra or []):
        dados = baixar_json(URL, params={"jobName": termo, "limit": 100})
        for j in (dados or {}).get("data", []):
            if j["id"] in vistos:
                continue
            vistos.add(j["id"])
            texto = f"{j.get('name','')} {j.get('description','')[:500]}"
            if not (SUPERIOR.search(texto) or j.get("type") == "vacancy_type_lecturer"):
                continue  # descarta educação básica/cursinho
            deadline = (j.get("applicationDeadline") or "")[:10]
            prazo = "/".join(reversed(deadline.split("-"))) if deadline else ""
            vagas.append(Vaga(
                titulo=j.get("name", ""),
                instituicao=j.get("careerPageName", "") or "ver anúncio",
                classificacao_instituicao="privada",
                natureza="emprego CLT (docente privado)",
                cidade=j.get("city", ""),
                estado=UF.get(j.get("state", ""), ""),
                modalidade=MODALIDADE.get(j.get("workplaceType", ""), "não informado"),
                titulacao_exigida=clf.classificar_titulacao(texto),
                data_publicacao="/".join(reversed((j.get("publishedDate") or "")[:10].split("-"))),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial=j.get("jobUrl", ""),
                fonte=f"Gupy (busca: {termo})",
                trecho_comprovacao=(j.get("description") or j.get("name", ""))[:400],
                confianca="alto",
            ))
            if len(vagas) >= max_por_fonte:
                return vagas
    return vagas

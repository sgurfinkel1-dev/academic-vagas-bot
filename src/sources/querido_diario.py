"""Diários oficiais municipais via API do Querido Diário (Open Knowledge Brasil)."""
import logging
from datetime import date, timedelta

from ..extractors.html_extractor import baixar_json
from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
URL = "https://queridodiario.ok.org.br/api/gazettes"


def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    vagas = []
    desde = (date.today() - timedelta(days=dias)).isoformat()
    for termo in termos:
        dados = baixar_json(URL, params={
            "querystring": f'"{termo}"', "published_since": desde,
            "size": min(max_por_fonte, 100), "sort_by": "descending_date",
        })
        for g in (dados or {}).get("gazettes", []):
            trechos = " ".join(g.get("excerpts", []))[:1000]
            texto = f"{termo} {trechos} {g.get('territory_name', '')}"
            prazo = clf.extrair_prazo(trechos)
            vagas.append(Vaga(
                titulo=f"{termo} — DO de {g.get('territory_name', '?')}",
                instituicao=g.get("territory_name", ""),
                classificacao_instituicao=clf.classificar_instituicao(texto) if clf.classificar_instituicao(texto) != "verificar manualmente" else "pública municipal",
                natureza=clf.classificar_natureza(texto),
                cidade=g.get("territory_name", ""),
                estado=g.get("state_code", ""),
                titulacao_exigida=clf.classificar_titulacao(trechos),
                data_publicacao=g.get("date", ""),
                prazo_inscricao=prazo,
                status=clf.status_por_prazo(prazo),
                link_oficial=g.get("url", ""),
                link_edital_pdf=g.get("url", "") if str(g.get("url", "")).endswith(".pdf") else "",
                fonte=f"Querido Diário (busca: {termo})",
                trecho_comprovacao=trechos[:300],
                confianca="médio",
                observacoes="Publicação em diário municipal; confirmar edital.",
            ))
    return vagas

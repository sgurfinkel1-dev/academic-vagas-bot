"""Diário Oficial do Estado de São Paulo (Imprensa Oficial)."""
import logging
import re
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import httpx

from ..extractors import llm_classifier as clf
from ..database.models import Vaga

log = logging.getLogger("bot")
BASE = "https://www.imprensaoficial.com.br"

def buscar(termos: list[str], dias: int = 30, max_por_fonte: int = 100) -> list[Vaga]:
    """Busca no DOE-SP via API XML (Imprensa Oficial SP).

    A API retorna resultado.xml com formato estruturado.
    Filtra por palavras-chave que indicam vaga: professor, docente, concurso, edital, processo seletivo.
    """
    vagas = []
    desde = (date.today() - timedelta(days=dias)).isoformat()

    for termo in termos:
        try:
            # API da Imprensa Oficial SP retorna XML
            r = httpx.get(f"{BASE}/api/consulta", params={
                "q": termo,
                "caderno": "oficial",
                "tipo_documento": "",
                "data_inicio": desde,
                "data_fim": date.today().isoformat(),
                "ordenacao": "data_decrescente",
            }, timeout=15)

            if r.status_code != 200:
                log.warning(f"DOE-SP: busca '{termo}' retornou {r.status_code}")
                continue

            # Parser XML ou JSON dependendo da resposta
            try:
                raiz = ET.fromstring(r.content)
                documentos = raiz.findall(".//documento")
            except ET.ParseError:
                # Se não for XML, tenta JSON (fallback)
                import json
                dados = r.json()
                documentos = dados.get("documentos", [])

            for doc in documentos[:max_por_fonte]:
                titulo = doc.get("titulo", "") if isinstance(doc, dict) else (doc.findtext("titulo") or "")
                texto = doc.get("texto", "") if isinstance(doc, dict) else (doc.findtext("texto") or "")
                data_pub = doc.get("data", "") if isinstance(doc, dict) else (doc.findtext("data") or "")
                link = doc.get("url", "") if isinstance(doc, dict) else (doc.findtext("url") or "")

                # Filtro: só vagas (keywords que indicam edital/concurso/processo seletivo)
                conteudo_completo = f"{titulo} {texto}".lower()
                if not any(kw in conteudo_completo for kw in ["professor", "docente", "concurso", "edital", "processo seletivo", "pesquisador"]):
                    continue

                # Evita portarias de nomeação (que citam o concurso mas não são edital)
                if "nomeação" in conteudo_completo or "exoneração" in conteudo_completo:
                    continue

                prazo = clf.extrair_prazo(texto)
                vagas.append(Vaga(
                    titulo=titulo[:200],
                    instituicao="São Paulo (DOE)",
                    classificacao_instituicao="pública estadual",
                    natureza=clf.classificar_natureza(conteudo_completo),
                    estado="SP",
                    titulacao_exigida=clf.classificar_titulacao(conteudo_completo),
                    data_publicacao=data_pub,
                    prazo_inscricao=prazo,
                    status=clf.status_por_prazo(prazo),
                    link_oficial=link or f"{BASE}/diario/",
                    fonte=f"DOE-SP (busca: {termo})",
                    trecho_comprovacao=(texto or titulo)[:600],
                    confianca="médio",
                ))
        except Exception as e:
            log.warning(f"DOE-SP: erro ao buscar '{termo}': {e}")
            continue

    return vagas

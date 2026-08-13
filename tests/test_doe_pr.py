"""DOE-PR: parser da busca do diário paranaense, contra resposta real da API.

Para regerar a fixture:
    GET https://dioe.pr.gov.br/busca/busca/buscar/query/0/di:AAAA-MM-DD/df:AAAA-MM-DD/?1=1&q=professor
e guarde um hit que vire vaga mais um que não vire.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.sources import doe_pr

FIXTURE = Path(__file__).parent / "fixtures" / "doe_pr_busca.json"


def _hits():
    if not FIXTURE.exists():
        pytest.skip("Fixture tests/fixtures/doe_pr_busca.json ausente")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["hits"]["hits"]


def test_pagina_real_vira_vaga():
    """Se isto falhar, o formato do Elasticsearch do DOE-PR mudou e buscar()
    passa a devolver lista vazia sem erro nenhum."""
    src = _hits()[0]["_source"]
    vagas = doe_pr._vagas_da_pagina(src, "professor")
    assert vagas, ("Página com processo seletivo de docente não virou Vaga — "
                   "o parser do DOE-PR quebrou.")
    v = vagas[0]
    assert v.estado == "PR"
    assert v.titulo and v.link_oficial.startswith("https://dioe.pr.gov.br")
    assert v.trecho_comprovacao


def test_pagina_sem_vaga_e_descartada():
    """A unidade indexada é a PÁGINA do PDF, com dez atos sem relação. Sem
    descartar página que só cita a palavra, a fonte vira gerador de ruído."""
    src = _hits()[1]["_source"]
    assert doe_pr._vagas_da_pagina(src, "professor") == []


def test_data_vai_com_zero_a_esquerda_no_caminho():
    """Ao contrário do DOE-SP, aqui a data é segmento de caminho e leva zero.
    Trocar o formato devolve 200 com zero resultados, sem erro."""
    from datetime import date
    url = doe_pr._url("professor", 0, date(2026, 8, 3), date(2026, 8, 13))
    assert "di:2026-08-03" in url and "df:2026-08-13" in url


def test_paginacao_comeca_em_zero():
    """query/0 é a primeira página. Começar em 1 pula 10 itens em silêncio."""
    from datetime import date
    assert "/query/0/" in doe_pr._url("x", 0, date(2026, 1, 1), date(2026, 1, 2))


def test_http_ruim_nao_quebra():
    resp = MagicMock(status_code=502, json=MagicMock(return_value={}))
    with patch("httpx.Client.get", return_value=resp):
        assert doe_pr.buscar(["professor"], dias=7, max_por_fonte=5) == []


def test_resposta_sem_hits_nao_quebra():
    resp = MagicMock(status_code=200, json=MagicMock(return_value={"hits": {"hits": []}}))
    with patch("httpx.Client.get", return_value=resp):
        assert doe_pr.buscar(["professor"], dias=7, max_por_fonte=5) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

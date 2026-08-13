"""Testes do doe_rs contra resposta real da API (tests/fixtures/doe_rs_busca.json).

A fixture guarda duas matérias reais da UERGS que só diferem na FASE do
certame: o EDITAL DE ABERTURA DE CONCURSOS DOCENTES 2024 (vaga de verdade) e a
HOMOLOGAÇÃO DO RESULTADO FINAL de 2026 (ruído). Ambas são "Editais" da mesma
entidade, com as mesmas palavras "concurso", "docente" e "UERGS" — ou seja,
nenhum filtro de tipo, de cargo ou de ato separa as duas. Só o filtro de fase
separa, e é por isso que ele existe. Se alguém afrouxar FASE_ENCERRADA, o
teste do ruído quebra.
"""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from src.sources import doe_rs

FIXTURE = Path(__file__).parent / "fixtures" / "doe_rs_busca.json"


@pytest.fixture(scope="module")
def dados():
    if not FIXTURE.exists():
        pytest.skip("Fixture tests/fixtures/doe_rs_busca.json ausente")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _par(dados, mid: int):
    """Devolve (item da busca, detalhe) de uma matéria da fixture."""
    item = next(i for i in dados["busca"]["collection"] if i["id"] == mid)
    return item, dados["detalhes"][str(mid)]


def test_edital_de_abertura_vira_vaga(dados):
    v = doe_rs._vaga(*_par(dados, 1161501), "docente")
    assert v is not None
    assert v.titulo.startswith("CONCURSO")
    assert "EDITAL DE ABERTURA" in v.titulo
    assert v.instituicao == ("Universidade Estadual do Rio Grande do Sul — "
                             "Gabinete da Reitoria")
    assert v.classificacao_instituicao == "pública estadual"
    assert v.estado == "RS"
    assert v.data_publicacao == "31/10/2024"
    assert v.link_oficial == "https://www.diariooficial.rs.gov.br/materia?id=1161501"
    assert v.fonte == "DOE-RS (busca: docente)"
    assert v.trecho_comprovacao


def test_homologacao_de_resultado_nao_e_vaga(dados):
    """Mesma UERGS, mesmo tipoMateria, mesmas palavras — muda só a fase."""
    assert doe_rs._vaga(*_par(dados, 1461628), "docente") is None


def test_ato_sem_cargo_nao_e_vaga(dados):
    """Edital de licitação tem "edital" no cabeçalho mas nenhum cargo docente."""
    item, det = _par(dados, 1161501)
    det = dict(det, conteudo="<p>EDITAL DE PREGÃO ELETRÔNICO Nº 9/2026 — "
                             "aquisição de material de expediente</p>")
    assert doe_rs._vaga(dict(item, texto="material de expediente"), det, "x") is None


def test_texto_limpa_lixo_do_editor_legado():
    """&nbsp;, <textopuro> e \\x01 (separador de célula) colam nas palavras."""
    sujo = "<p><b>EDITAL</b>&nbsp;Nº 1</p><textopuro>docente\x01UERGS</textopuro>"
    assert doe_rs._texto(sujo) == "EDITAL Nº 1 docente UERGS"


def test_titulo_comeca_no_ato_nao_no_nome_do_orgao():
    cab = ("UERGS - UNIVERSIDADE ESTADUAL DO RIO GRANDE DO SUL ESTADO DO RIO "
           "GRANDE DO SUL CONCURSOS PÚBLICOS Nº 02 a 24/2024 EDITAL DE ABERTURA")
    assert doe_rs._titulo(cab).startswith("CONCURSOS PÚBLICOS Nº 02")


def test_data_vai_com_zero_a_esquerda(monkeypatch):
    """Armadilha silenciosa: 2026-8-1 devolve 200 com collectionSize=0."""
    visto = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"collection": [], "collectionSize": 0, "pageSize": 10}

    def _get(self, url, params=None, **kw):
        visto.update(params or {})
        return _Resp()

    monkeypatch.setattr(httpx.Client, "get", _get)
    doe_rs.buscar(["professor"], dias=30)
    assert len(visto["dataIni"]) == len("AAAA-MM-DD")
    assert visto["dataFim"] == date.today().isoformat()
    assert visto["tipoDiario"] == "DOE"  # minúsculo devolve zero resultados


def test_erro_de_rede_nao_derruba_a_coleta(monkeypatch):
    def _explode(self, *a, **kw):
        raise httpx.ConnectError("DNS falhou")

    monkeypatch.setattr(httpx.Client, "get", _explode)
    assert doe_rs.buscar(["professor"], dias=7, max_por_fonte=5) == []

"""Testes do doe_sc contra resposta REAL salva, sem rede.

A fixture é a resposta de verdade do POST /apis/busca-materia (13/08/2026),
só com o texto encurtado. Os três itens não são exemplo inventado: são o pior
caso de cada categoria que a medição sobre 625 publicações revelou.
"""
import json
from pathlib import Path

import pytest

from src.sources import doe_sc

FIXTURE = Path(__file__).parent / "fixtures" / "doe_sc_busca.json"


@pytest.fixture
def materias():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["materias"]


@pytest.fixture
def edital(materias):
    """PROCESSO SELETIVO 05/2026 da UDESC — Professor Substituto."""
    return materias[0]


@pytest.fixture
def portaria(materias):
    """Portaria de designação da UDESC: cita professor, não abre vaga."""
    return materias[1]


@pytest.fixture
def inexigibilidade(materias):
    """ENA contratando um docente nominal. Chega como assunto=EDITAL, mas é
    contratação direta de um professor já escolhido — não é vaga aberta."""
    return materias[2]


def test_edital_de_docente_vira_vaga(edital):
    v = doe_sc._vaga(edital, "professor")
    assert v is not None
    assert v.estado == "SC"
    assert v.fonte == "DOE-SC (busca: professor)"
    assert v.data_publicacao == "2026-07-22"
    assert v.link_oficial.startswith("https://portal.doe.sea.sc.gov.br/")
    assert "PROCESSO SELETIVO Nº 05/2026" in v.titulo
    assert v.natureza == "professor substituto"


def test_portaria_que_so_cita_professor_e_barrada(portaria):
    """O filtro que importa: sem ele entravam 297 de 625 publicações, quase
    todas portaria de designação/retificação citando um professor."""
    assert doe_sc._vaga(portaria, "professor") is None


def test_inexigibilidade_de_licitacao_e_barrada(inexigibilidade):
    """assunto=EDITAL não basta: 21 das 28 que passavam pelo assunto eram este
    caso — contratação direta de docente nominal pela Escola de Governo."""
    assert doe_sc._vaga(inexigibilidade, "professor") is None


def test_prazo_pega_o_ultimo_termino_do_bloco_de_inscricoes(edital):
    """O edital lista 'Término' duas vezes (isento 29/07, pagante 05/08).
    Vale o prazo mais longo, senão a vaga é marcada como vencida antes da hora.
    extrair_prazo() do projeto não pega este formato — daí o complemento local.
    """
    assert doe_sc._prazo(edital["resumo"]) == "05/08/2026"


def test_instituicao_sai_do_texto_quando_a_secao_e_generica(edital):
    """categoria='Concursos' é seção do diário, não órgão. O nome da UDESC só
    existe dentro do texto."""
    v = doe_sc._vaga(edital, "professor")
    assert "UDESC" in v.instituicao


def test_instituicao_usa_a_categoria_quando_ela_nomeia_o_orgao(portaria):
    assert doe_sc._instituicao(portaria, "") == portaria["categoria"]


def test_classificacao_nao_cai_no_bug_do_edital(edital):
    """`ital\\b` na regra de 'instituto público' do llm_classifier casa com a
    palavra EDITAL. Sem o contorno, toda publicação daqui viraria instituto
    público — inclusive a UDESC, que é estadual."""
    v = doe_sc._vaga(edital, "professor")
    assert v.classificacao_instituicao == "pública estadual"


def test_buscar_nao_derruba_a_coleta_quando_a_rede_falha(monkeypatch):
    """Erro de rede vira warning e lista vazia, nunca exceção: uma fonte fora
    do ar não pode abortar a coleta das outras."""
    import httpx

    def explode(self, *a, **k):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx.Client, "post", explode)
    assert doe_sc.buscar(["professor"], dias=30) == []


def test_buscar_monta_vagas_a_partir_da_resposta(monkeypatch, materias):
    """Uma página só; o loop tem de parar (len(itens) < PAGINA) e não repaginar."""
    import httpx

    chamadas = []

    class Resp:
        status_code = 200

        def json(self):
            return {"total": 3, "materias": materias}

    def fake_post(self, url, json=None, **k):
        chamadas.append(json)
        return Resp()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    vagas = doe_sc.buscar(["professor"], dias=30)
    assert len(chamadas) == 1
    assert chamadas[0]["resumo"] is False  # false = COM texto; true devolve vazio
    assert len(vagas) == 1
    assert "UDESC" in vagas[0].instituicao


def test_buscar_nao_repete_a_mesma_materia_em_termos_diferentes(monkeypatch, materias):
    import httpx

    class Resp:
        status_code = 200

        def json(self):
            return {"total": 3, "materias": materias}

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, json=None, **k: Resp())
    vagas = doe_sc.buscar(["professor", "concurso"], dias=30)
    assert len(vagas) == 1

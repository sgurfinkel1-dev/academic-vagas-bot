"""Testes do DOE-MG contra resposta real da API, sem rede.

A fixture tests/fixtures/doe_mg_pesquisa.json é a resposta literal de
13/08/2026 para TextoPesquisa=UEMG no dia 11/08/2026 (Diário do Executivo,
TamanhoPagina=4): três atos de ruído — duas listas de licença-prêmio e uma
exoneração — e um edital de verdade (EXTRATO DO EDITAL DE SELEÇÃO 04/2026 do
Programa de Bolsas de Professor Consultor da UEMG). É exatamente a proporção
que a fonte entrega, e é isso que os testes precisam provar que o filtro sabe
separar.

Para regerar: POST em /api/v1/Autenticacao/Autenticar com corpo {} para obter o
JWT, depois GET em /api/v1/Pesquisa/PesquisarJornaisPaginados com
Authorization: Bearer <JWT>.

Rodar:  python -m pytest tests/test_doe_mg.py -q
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.sources import doe_mg

FIXTURE = Path(__file__).parent / "fixtures" / "doe_mg_pesquisa.json"


@pytest.fixture
def itens():
    if not FIXTURE.exists():
        pytest.skip("Fixture tests/fixtures/doe_mg_pesquisa.json ausente")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["dados"]


def _edital(itens):
    return next(i for i in itens if "EDITAL DE SELECAO" in i["textoResultado"])


def test_edital_real_vira_vaga(itens):
    v = doe_mg._vaga(_edital(itens), "UEMG")
    assert v is not None, (
        "O edital de seleção da UEMG na resposta real da API não virou Vaga — "
        "o formato do DOE-MG mudou e buscar() devolve vazio em silêncio.")
    assert v.estado == "MG"
    assert v.instituicao.startswith("Universidade do Estado de Minas Gerais")
    assert v.data_publicacao == "2026-08-11"
    assert v.trecho_comprovacao
    assert v.link_oficial.startswith("https://www.jornalminasgerais.mg.gov.br/edicao-do-dia?dados=")


def test_titulo_comeca_no_ato_nao_no_lixo_de_pagina(itens):
    """O trecho vem com o rodapé de cobrança do diário na frente ('5 cm -10
    2245743 - 1'); sem o corte o título ficava ilegível."""
    v = doe_mg._vaga(_edital(itens), "UEMG")
    assert v.titulo.startswith("EXTRATO DO EDITAL DE SELECAO")


def test_ruido_e_descartado(itens):
    """Dos 4 atos reais da fixture, 3 são ruído: duas listas de licença-prêmio
    (citam a UEMG, não abrem vaga) e uma exoneração assinada pelo Reitor."""
    ruidos = [i for i in itens if i is not _edital(itens)]
    assert len(ruidos) == 3
    assert all(doe_mg._vaga(i, "UEMG") is None for i in ruidos)


def test_exoneracao_nao_passa_mesmo_citando_professor():
    """Medido em 13/08/2026: exigir só cargo deixava passar 140 de 374 trechos;
    exigir também ato de vaga derruba para 14, barrar posse/exoneração para 10
    e exigir contexto de ensino superior para 5 — todos editais de verdade."""
    item = {"idJornal": 1, "pagina": 9, "dataPublicacao": "2026-08-11T00:00:00",
            "textoResultado": "Universidade do Estado de Minas Gerais - UEMG "
                              "O Reitor exonera, a pedido, o professor titular "
                              "aprovado no Edital UEMG n 04/2024"}
    assert doe_mg._vaga(item, "UEMG") is None


def test_professor_de_educacao_basica_nao_passa():
    """O Diário do Executivo de MG é, em volume, diário de atos de pessoal da
    rede básica estadual — é o ruído dominante da fonte."""
    item = {"idJornal": 1, "pagina": 12, "dataPublicacao": "2026-08-11T00:00:00",
            "textoResultado": "Secretaria de Estado de Educacao, edital de "
                              "convocacao dos integrantes da carreira de "
                              "Professor de Educacao Basica"}
    assert doe_mg._vaga(item, "professor") is None


def test_acento_ausente_no_pdf_nao_quebra_o_filtro():
    """A extração de texto do PDF perde os acentos: 'magisterio', não
    'magistério'. Se os padrões voltarem a ser acentuados, a fonte zera."""
    item = {"idJornal": 1, "pagina": 70, "dataPublicacao": "2026-08-11T00:00:00",
            "textoResultado": "Unimontes CONCURSO PUBLICO para provimento de "
                              "cargos da carreira de magisterio superior"}
    v = doe_mg._vaga(item, "concurso")
    assert v is not None
    assert "Unimontes" in v.instituicao


def test_auth_falha_nao_derruba_a_coleta():
    with patch("httpx.Client.post", side_effect=__import__("httpx").ConnectError("dns")):
        assert doe_mg.buscar(["professor"], dias=7, max_por_fonte=5) == []


def test_http_ruim_nao_quebra():
    auth = MagicMock(status_code=200, json=MagicMock(return_value={"dados": "tok"}))
    auth.raise_for_status = MagicMock()
    ruim = MagicMock(status_code=503, json=MagicMock(return_value={}))
    with patch("httpx.Client.post", return_value=auth), \
         patch("httpx.Client.get", return_value=ruim):
        assert doe_mg.buscar(["professor"], dias=7, max_por_fonte=5) == []


def test_buscar_monta_vaga_a_partir_da_resposta_real(itens):
    """buscar() ponta a ponta com a rede trocada pela fixture."""
    auth = MagicMock(status_code=200, json=MagicMock(return_value={"dados": "tok"}))
    auth.raise_for_status = MagicMock()
    corpo = {"dados": itens, "paginaAtual": 1, "totalDePaginas": 1,
             "totalDeRegistros": len(itens), "erros": []}
    ok = MagicMock(status_code=200, json=MagicMock(return_value=corpo))
    with patch("httpx.Client.post", return_value=auth), \
         patch("httpx.Client.get", return_value=ok):
        vagas = doe_mg.buscar(["UEMG"], dias=30, max_por_fonte=10)
    assert len(vagas) == 1
    # a fonte nomeia o termo que achou; as âncoras de cargo são consultadas
    # antes do que o chamador pediu (ver _termos_uteis), então aqui vem uma delas
    assert vagas[0].fonte.startswith("DOE-MG (busca: ")


def test_frase_do_config_e_trocada_por_palavra_util():
    """TextoPesquisa casa a frase inteira: 'professor substituto' devolve quase
    nada e 'professor' devolve 7. Sem esta troca a fonte parece seca com a lista
    de termos do config, que é quase toda de frases."""
    uteis = doe_mg._termos_uteis(["professor substituto", "concurso docente",
                                  "epidemiologia", "provas e títulos"])
    assert "professor" in uteis, "âncora de cargo tem de entrar sempre"
    assert "epidemiologia" in uteis, "palavra única do chamador tem de sobreviver"
    assert "professor substituto" not in uteis, "frase não casa nesta API"
    assert all(len(t.split()) == 1 for t in uteis), "só palavras únicas"


def test_termos_repetidos_nao_duplicam_a_mesma_publicacao(itens):
    """'edital UEMG' casa com professor, UEMG e concurso ao mesmo tempo."""
    auth = MagicMock(status_code=200, json=MagicMock(return_value={"dados": "tok"}))
    auth.raise_for_status = MagicMock()
    corpo = {"dados": itens, "paginaAtual": 1, "totalDePaginas": 1,
             "totalDeRegistros": len(itens), "erros": []}
    ok = MagicMock(status_code=200, json=MagicMock(return_value=corpo))
    with patch("httpx.Client.post", return_value=auth), \
         patch("httpx.Client.get", return_value=ok):
        vagas = doe_mg.buscar(["UEMG", "professor", "concurso"], dias=30, max_por_fonte=10)
    assert len(vagas) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

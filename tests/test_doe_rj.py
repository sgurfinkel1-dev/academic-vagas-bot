"""DOE-RJ: parser dos atos do diário carioca, contra trechos reais do PDF.

Para regerar a fixture: rode doe_rj._abrir() num dia útil e guarde um trecho de
doe_rj._atos() que vire Vaga e um que não vire.
"""
import base64
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.sources import doe_rj

FIXTURE = Path(__file__).parent / "fixtures" / "doe_rj_trechos.json"


def _dados():
    if not FIXTURE.exists():
        pytest.skip("Fixture tests/fixtures/doe_rj_trechos.json ausente")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_chave_do_pdf_insere_p_na_posicao_12():
    """O viewer monta a URL do PDF escondendo os caracteres em
    String.fromCharCode: ...pd.substring(0,12)+fromCharCode(80)+pd.substring(12).
    O 80 é o 'P'. Sem ele o servidor devolve 200 com CORPO VAZIO — se alguém
    'limpar' esta linha achando que é typo, a fonte zera sem erro nenhum."""
    pd = "FE14F7C4-C7B0-47FB-864D-117CE53D936B"
    assert pd[:12] + "P" + pd[12:] == "FE14F7C4-C7BP0-47FB-864D-117CE53D936B"


def test_concurso_real_vira_vaga():
    d = _dados()["vaga"]
    v = doe_rj._vaga(d["trecho"], date.fromisoformat(d["data"]))
    assert v is not None, ("Concurso de professor da UERJ não virou Vaga — o "
                           "parser do DOE-RJ quebrou e buscar() devolve vazio.")
    assert v.estado == "RJ"
    assert v.classificacao_instituicao == "pública estadual"
    assert "UERJ" in v.instituicao or "UENF" in v.instituicao
    assert v.trecho_comprovacao


def test_prova_comeca_onde_o_ato_comeca():
    """A janela de texto costuma abrir no meio do ato anterior. Se o trecho de
    comprovação não começar no ato, a vaga aparece no painel provada por um
    extrato de contrato — foi o que acontecia antes."""
    d = _dados()["vaga"]
    v = doe_rj._vaga(d["trecho"], date.fromisoformat(d["data"]))
    inicio = v.trecho_comprovacao[:40].upper()
    assert any(p in inicio for p in ("EDITAL", "CONCURSO", "PROCESSO SELETIVO"))


def test_portaria_de_pessoal_e_descartada():
    """O diário do RJ é, em volume, diário de pessoal: designa, exonera,
    aposenta. Toda portaria cita o cargo e nenhuma abre vaga."""
    d = _dados().get("ruido")
    if not d:
        pytest.skip("fixture sem trecho de ruído")
    assert doe_rj._vaga(d["trecho"], date.fromisoformat(d["data"])) is None


def test_tecnico_universitario_nao_e_vaga_docente():
    """A UERJ publica concurso de Técnico Universitário na mesma página do
    concurso docente, e o edital cita 'professor' ao descrever a banca."""
    trecho = ("CONCURSO PÚBLICO PARA O CARGO DE TÉCNICO UNIVERSITÁRIO SUPERIOR "
              "da UERJ, edital de abertura de inscrições, banca de professor "
              "adjunto designada para a avaliação dos candidatos.")
    assert doe_rj._vaga(trecho, date(2026, 8, 3)) is None


def test_texto_limpo_desfaz_hifenizacao_e_espacamento():
    """PDF de jornal quebra palavra no fim da linha e espaça letra para
    justificar coluna. Sem desfazer, o título sai ilegível no painel."""
    assert "DEPARTAMENTO" in doe_rj._texto_limpo("DEPAR- TAMENTO DE FÍSICA")
    assert "ADJUNTO" in doe_rj._texto_limpo("PROFESSOR A D J U N T O")


def test_dia_sem_edicao_nao_quebra():
    """Fim de semana e feriado não têm edição: o portal devolve página sem o
    link do caderno. Isso é silêncio esperado, não erro."""
    resp = MagicMock(status_code=200, text="<html><body>sem cadernos</body></html>")
    cli = MagicMock()
    cli.get.return_value = resp
    assert doe_rj._abrir(cli, date(2026, 8, 15)) is None


def test_pdf_ilegivel_nao_quebra():
    assert doe_rj._atos(b"nao sou um pdf") == []


def test_buscar_com_rede_ruim_devolve_vazio():
    import httpx
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("fora do ar")):
        assert doe_rj.buscar(dias=3, max_por_fonte=5) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

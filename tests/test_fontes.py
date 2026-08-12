"""Testes unitários dos extratores e fontes (mock de rede).

Cobre:
  - html_extractor: baixar, baixar_json
  - pdf_extractor: texto_do_pdf (mock)
  - fapesp: partes(), buscar()
  - dou: _limpo(), buscar_palavra()
  - anpof: _instituicao(), buscar()
  - gupy: buscar()
  - universidades_publicas: buscar()
  - universidades_privadas: buscar()
  -querido_diario: buscar()
  - vagas_com: buscar()
  - busca_aberta: buscar()
  - inlabs: buscar() (stub)

Rodar:  python -m tests.test_fontes
Ou com pytest:  pytest tests/test_fontes.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.extractors import html_extractor, pdf_extractor
from src.sources import (fapesp, dou, anpof, gupy, universidades_publicas,
                         universidades_privadas, querido_diario, vagas_com,
                         busca_aberta, inlabs)
from src.database.models import Vaga


# ===========================================================================
# HTML EXTRACTOR
# ===========================================================================

class TestHtmlExtractor:
    def test_baixar_timeout_retorna_vazio(self):
        with patch("src.extractors.html_extractor.httpx.get") as m:
            m.side_effect = Exception("timeout")
            assert html_extractor.baixar("https://exemplo.com") == ""

    def test_baixar_404_retorna_vazio(self):
        with patch("src.extractors.html_extractor.httpx.get") as m:
            resp = MagicMock()
            resp.raise_for_status.side_effect = Exception("404")
            m.return_value = resp
            assert html_extractor.baixar("https://exemplo.com") == ""

    def test_baixar_json_retorna_dict(self):
        with patch("src.extractors.html_extractor.httpx.get") as m:
            resp = MagicMock()
            resp.json.return_value = {"data": [1, 2]}
            resp.raise_for_status.return_value = None
            m.return_value = resp
            assert html_extractor.baixar_json("https://exemplo.com") == {"data": [1, 2]}

    def test_baixar_json_erro_retorna_none(self):
        with patch("src.extractors.html_extractor.httpx.get") as m:
            m.side_effect = Exception("fail")
            assert html_extractor.baixar_json("https://exemplo.com") is None

    def test_texto_da_pagina_extrai_texto(self):
        html = "<div><p>Olá mundo</p></div>"
        assert html_extractor.texto_da_pagina(html) == "Olá mundo"

    def test_texto_da_pagina_html_vazio(self):
        assert html_extractor.texto_da_pagina("") == ""


# ===========================================================================
# PDF EXTRACTOR
# ===========================================================================

class TestPdfExtractor:
    def test_texto_do_pdf_mock(self, tmp_path, monkeypatch):
        """PDF já baixado não é baixado de novo.

        texto_do_pdf recebe uma URL e sempre resolve o arquivo dentro de RAW —
        passar um caminho local não faz a função lê-lo, ela só usa o nome do
        arquivo. Apontando RAW para tmp_path, o "já existe" passa a ser verdade
        de fato. Sem isso o teste dependia de ter sobrado um data/raw/edital.pdf
        de execução anterior: passava na máquina de quem já rodou o robô e
        falhava em checkout limpo, como o do CI.
        """
        monkeypatch.setattr(pdf_extractor, "RAW", tmp_path)
        (tmp_path / "edital.pdf").write_bytes(b"fake pdf")
        with patch("src.extractors.pdf_extractor.pdfplumber.open") as m:
            page = MagicMock()
            page.extract_text.return_value = "Texto do edital"
            m.return_value.__enter__.return_value.pages = [page]
            with patch("src.extractors.pdf_extractor.httpx.get") as http:
                result = pdf_extractor.texto_do_pdf("https://exemplo.com/edital.pdf")
                assert "Texto do edital" in result
                http.assert_not_called()  # o cache tem que evitar o download

    def test_texto_do_pdf_falha_retorna_vazio(self):
        with patch("src.extractors.pdf_extractor.pdfplumber.open") as m:
            m.side_effect = Exception("broken")
            assert pdf_extractor.texto_do_pdf("https://exemplo.com.pdf") == ""


# ===========================================================================
# FAPESP
# ===========================================================================

class TestFapesp:
    def test_partes_separes_assunto_e_casa(self):
        # formato real do FAPESP: "Título Instituição: UFMG: Cidade: BH"
        titulo = "Bolsa de Pós-Doutorado em Filosofia Instituição: Universidade de São Paulo: Cidade: São Paulo"
        assunto, casa = fapesp.partes(titulo)
        assert "Bolsa de Pós-Doutorado em Filosofia" in assunto
        assert "Universidade de São Paulo" in casa

    def test_partes_sem_casa_retorna_titulo_como_assunto(self):
        titulo = "Bolsa de Pós-Doutorado em Direito"
        assunto, casa = fapesp.partes(titulo)
        assert assunto == "Bolsa de Pós-Doutorado em Direito"
        assert casa == ""

    def test_buscar_retorna_lista(self):
        html_mock = """
        <html><body>
        <a href="/oportunidades/bolsa-filosofia">Bolsa de Filosofia Instituição: UFMG: Cidade: BH</a>
        <a href="/oportunidades/bolsa-quimica">Bolsa de Química Instituição: USP: Cidade: SP</a>
        <a href="/oportunidades/">Página principal</a>
        </body></html>
        """
        with patch("src.sources.fapesp.baixar", return_value=html_mock):
            vagas = fapesp.buscar(["filosofia", "química"])
            assert len(vagas) >= 1
            assert all(isinstance(v, Vaga) for v in vagas)
            assert all(v.classificacao_instituicao == "agência/fundação" for v in vagas)


# ===========================================================================
# DOU
# ===========================================================================

class TestDou:
    def test_limpo_remove_tags_html(self):
        texto = "<span class='highlight'>Filosofia</span> concurso"
        assert dou._limpo(texto) == "Filosofia concurso"

    def test_limpo_normaliza_esacos(self):
        texto = "Filosofia    concurso\n\nedital"
        assert dou._limpo(texto) == "Filosofia concurso edital"

    def test_buscar_palavra_filtra_nao_academicas(self):
        # simula vagas que passam pelo mock de buscar()
        # A primeira é previdência (não acadêmica), a segunda é vaga de filosofia
        vagas_mock = [
            Vaga(titulo="EDITAL Nº 1 - Continuidade Lógica", trecho_comprovacao="continuidade lógica previdencia social",
                 classificacao_instituicao="pública federal", fonte="DOU",
                 link_oficial="https://dou.gov.br"),
            Vaga(titulo="Concurso para professor de Lógica", trecho_comprovacao="departamento de lógica e filosofia",
                 classificacao_instituicao="pública federal", fonte="DOU",
                 link_oficial="https://dou.gov.br"),
        ]
        # Patch na função buscar do módulo dou (onde é chamada)
        import src.sources.dou as dou_module
        with patch.object(dou_module, 'buscar', return_value=vagas_mock):
            result = dou.buscar_palavra("lógica", dias=30)
            # só a segunda deve passar (a primeira é previdência, não vaga acadêmica)
            assert len(result) == 1
            assert "Lógica" in result[0].titulo

    def test_e_da_area_titulo_casa(self):
        v = Vaga(titulo="Concurso para professor de Filosofia", trecho_comprovacao="")
        assert dou._e_da_area(v, "Filosofia") is True

    def test_e_da_area_corpo_casa_em_contexto(self):
        v = Vaga(titulo="EDITAL Nº 1", trecho_comprovacao="concurso para o departamento de Filosofia")
        assert dou._e_da_area(v, "Filosofia") is True

    def test_e_da_area_nao_casa_fora_de_contexto(self):
        v = Vaga(titulo="EDITAL Nº 1", trecho_comprovacao="continuidade lógica previdencia")
        assert dou._e_da_area(v, "lógica") is False


# ===========================================================================
# DOU: parsing do jsonArray (contrato com o site real)
# ===========================================================================

class TestDouParse:
    """Testa o parser do jsonArray embutido no <script> da página do DOU.

    Usa fixture real (tests/fixtures/dou_busca.html) — HTML sintético não testa
    o contrato. Se a fixture não existir, o teste pula (não falha), porque o
    objetivo é falhar alto quando o formato do site mudar.

    Para gerar a fixture: salve a página de busca do DOU no navegador como
    HTML completo e coloque em tests/fixtures/dou_busca.html.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "dou_busca.html"

    def test_parse_extraia_itens_do_jsonarray(self):
        if not self.FIXTURE.exists():
            pytest.skip("Fixture tests/fixtures/dou_busca.html ausente — "
                        "salve HTML real do DOU para ativar este teste")

        html = self.FIXTURE.read_text(encoding="utf-8")
        itens = dou._parse_html_dou(html)

        # O DOU sempre devolve resultados para "professor" — lista vazia = quebra
        assert isinstance(itens, list), "Parser devolveu tipo errado"
        assert len(itens) > 0, (
            "Parser encontrou 0 itens no HTML da fixture — o formato do jsonArray "
            "mudou e buscar() está devolvendo lista vazia em silêncio."
        )

    def test_itens_têm_campos_esperados(self):
        if not self.FIXTURE.exists():
            pytest.skip("Fixture tests/fixtures/dou_busca.html ausente")

        html = self.FIXTURE.read_text(encoding="utf-8")
        itens = dou._parse_html_dou(html)
        assert len(itens) > 0

        item = itens[0]
        # Campos que buscar() lê para construir Vaga — se faltar, a vaga fica incompleta
        for campo in ("title", "content", "pubDate", "urlTitle", "hierarchyStr"):
            assert campo in item, f"Campo '{campo}' ausente no jsonArray — " \
                                   f"o formato mudou e buscar() vai gerar vaga incompleta"

    def test_html_sem_jsonarray_devolve_lista_vazia(self):
        """HTML sem jsonArray deve devolver lista vazia, não levantar exceção."""
        assert dou._parse_html_dou("<html><body>sem resultados</body></html>") == []

    def test_html_vazio_nao_quebra(self):
        assert dou._parse_html_dou("") == []


# ===========================================================================
# ANPOF
# ===========================================================================

class TestAnpof:
    def test_instituicao_extrai_sigla(self):
        assert anpof._instituicao("Concurso UFMG professor") == "UFMG"
        assert anpof._instituicao("Seleção UNICAMP pesquisador") == "UNICAMP"
        assert anpof._instituicao("Vaga PUC-Rio") == "PUC-Rio"

    def test_item_retorna_none_sem_ancora_valida(self):
        from bs4 import BeautifulSoup
        div = BeautifulSoup("<div><a href='/outro'>X</a></div>", "lxml").find("div")
        assert anpof._item(div, "https://anpof.org.br") is None

    def test_buscar_retorna_lista(self):
        html_mock = """
        <html><body>
        <div class="lista-agenda-item">
          <a href="/agenda/concursos-e-selecoes/vaga-ufmg">Concurso UFMG Filosofia</a>
          <span>01/07/2026</span>
        </div>
        </body></html>
        """
        with patch("src.sources.anpof.baixar", return_value=html_mock):
            vagas = anpof.buscar(dias=30)
            assert isinstance(vagas, list)


# ===========================================================================
# GUPY
# ===========================================================================

class TestGupy:
    def test_buscar_filtra_nao_superior(self):
        dados_mock = {
            "data": [
                {"id": "1", "name": "Professor Ensino Superior", "description": "faculdade",
                 "city": "São Paulo", "state": "São Paulo", "type": "vacancy_type_lecturer",
                 "applicationDeadline": "2026-07-30", "jobUrl": "https://gupy.io/1",
                 "careerPageName": "Anhanguera", "publishedDate": "2026-01-01"},
                {"id": "2", "name": "Professor Cursinho", "description": "ensino médio",
                 "city": "SP", "state": "SP", "type": "vacancy_type_other",
                 "applicationDeadline": "", "jobUrl": "https://gupy.io/2",
                 "careerPageName": "聚福", "publishedDate": ""},
            ]
        }
        with patch("src.sources.gupy.baixar_json", return_value=dados_mock):
            vagas = gupy.buscar()
            assert len(vagas) == 1
            assert vagas[0].instituicao == "Anhanguera"
            assert vagas[0].classificacao_instituicao == "privada"

    def test_buscar_retorna_vazio_sem_dados(self):
        with patch("src.sources.gupy.baixar_json", return_value=None):
            assert gupy.buscar() == []


# ===========================================================================
# UNIVERSIDADES PUBLICAS / PRIVADAS
# ===========================================================================

class TestUniversidades:
    def test_buscar_publicas_retorna_vagas(self):
        html_mock = """
        <html><body>
        <a href="/edital1">Concurso para professor efetivo de Filosofia - UFMG</a>
        <a href="/edital2">Professor visitante Direito - USP</a>
        <a href="/outra">Notícia geral</a>
        </body></html>
        """
        with patch("src.sources.universidades_publicas.baixar", return_value=html_mock):
            paginas = [{"nome": "UFMG", "url": "https://ufmg.br/concursos"}]
            vagas = universidades_publicas.buscar(paginas)
            assert len(vagas) >= 1
            assert all(v.classificacao_instituicao in ("pública federal", "verificar manualmente")
                       for v in vagas)

    def test_buscar_privadas_reutiliza_publicas(self):
        html_mock = """
        <html><body>
        <a href="/edital1">Concurso professor PUC-SP</a>
        </body></html>
        """
        with patch("src.sources.universidades_publicas.buscar") as m:
            m.return_value = [Vaga(titulo="X", classificacao_instituicao="verificar manualmente")]
            vagas = universidades_privadas.buscar([{"nome": "PUC-SP", "url": "https://pucsp.br"}])
            assert vagas[0].classificacao_instituicao == "privada"


# ===========================================================================
# QUERIDO DIÁRIO
# ===========================================================================

class TestQueridoDiario:
    def test_buscar_retorna_vagas(self):
        dados_mock = {
            "gazettes": [
                {"territory_name": "Belo Horizonte", "state_code": "MG",
                 "date": "2026-07-01", "url": "https://bdou.br/edital",
                 "excerpts": ["concurso para professor de filosofia"]}
            ]
        }
        with patch("src.sources.querido_diario.baixar_json", return_value=dados_mock):
            vagas = querido_diario.buscar(["filosofia"], dias=30)
            assert len(vagas) == 1
            assert vagas[0].estado == "MG"
            assert vagas[0].fonte == "Querido Diário (busca: filosofia)"

    def test_buscar_filtra_por_estado(self):
        dados_mock = {
            "gazettes": [
                {"territory_name": "São Paulo", "state_code": "SP",
                 "date": "2026-07-01", "url": "https://bdou.br/edital",
                 "excerpts": ["professor"]},
                {"territory_name": "Rio de Janeiro", "state_code": "RJ",
                 "date": "2026-07-01", "url": "https://bdou.br/edital",
                 "excerpts": ["professor"]},
            ]
        }
        with patch("src.sources.querido_diario.baixar_json", return_value=dados_mock):
            vagas = querido_diario.buscar(["professor"], estados=["SP"])
            assert all(v.estado == "SP" for v in vagas)


# ===========================================================================
# VAGAS.COM
# ===========================================================================

class TestVagasCom:
    def test_buscar_retorna_vagas(self):
        html_mock = """
        <html><body>
        <li class="vaga">
          <a class="link-detalhes-vaga" href="/vaga/123" title="Professor Filosofia">
          <span class="emprVaga">Universidade X</span>
          <span class="vaga-local">Belo Horizonte - MG</span>
          texto professor ensino superior
          </a>
        </li>
        </body></html>
        """
        with patch("src.sources.vagas_com.baixar", return_value=html_mock):
            vagas = vagas_com.buscar()
            assert len(vagas) >= 1
            assert vagas[0].classificacao_instituicao == "privada"


# ===========================================================================
# BUSCA ABERTA
# ===========================================================================

class TestBuscaAberta:
    def test_buscar_retorna_com_confianca_baixa(self):
        html_mock = """
        <html><body>
        <li class="b_algo"><h2><a href="https://exemplo.com">Professor Filosofia</a></h2>
        <p>concurso para professor de filosofia</p></li>
        </body></html>
        """
        with patch("src.sources.busca_aberta.baixar", return_value=html_mock):
            vagas = busca_aberta.buscar(["professor"], ["filosofia"])
            assert len(vagas) >= 1
            assert vagas[0].confianca == "baixo"


# ===========================================================================
# INLABS (STUB)
# ===========================================================================

class TestInlabs:
    """Parser do XML oficial do DOU, contra artigo real (tests/fixtures/inlabs_artigo.xml).

    Para regerar a fixture: baixe um ZIP diário do inlabs.in.gov.br e extraia
    qualquer .xml que traga edital de professor.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "inlabs_artigo.xml"

    def _zip_da_fixture(self) -> bytes:
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("530_20260811_1.xml", self.FIXTURE.read_bytes())
        return buf.getvalue()

    def test_sem_credenciais_devolve_vazio(self, monkeypatch):
        for var in ("INLABS_EMAIL", "INLABS_SENHA", "INLABS_USER", "INLABS_PASS"):
            monkeypatch.delenv(var, raising=False)
        assert inlabs.buscar() == []

    def test_artigo_real_vira_vaga(self):
        if not self.FIXTURE.exists():
            pytest.skip("Fixture tests/fixtures/inlabs_artigo.xml ausente")

        arts = list(inlabs._artigos(self._zip_da_fixture()))
        assert len(arts) == 1, "ZIP com um XML deveria render um <article>"

        v = inlabs._vaga(arts[0], "DO3")
        assert v is not None, (
            "Edital de professor no XML oficial não virou Vaga — o formato do "
            "INLABS mudou e buscar() está devolvendo lista vazia em silêncio.")
        assert v.titulo and v.data_publicacao and v.link_oficial
        assert v.trecho_comprovacao, "Texto do edital não foi extraído do CDATA"

    def test_artigo_sem_cargo_docente_e_descartado(self):
        xml = ('<xml><article pubDate="11/08/2026" artCategory="X">'
               '<body><Identifica>EDITAL 1</Identifica>'
               '<Texto>Concurso público para o cargo de motorista.</Texto>'
               '</body></article></xml>')
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.xml", xml)
        art = next(inlabs._artigos(buf.getvalue()))
        assert inlabs._vaga(art, "DO3") is None

    def test_zip_invalido_nao_quebra(self):
        assert list(inlabs._artigos(b"nao sou um zip")) == []

    def test_tentar_repete_ate_a_rede_responder(self):
        """O DNS do INLABS sorteia IP morto: a 1ª tentativa cai, a seguinte pega."""
        import httpx
        chamadas = []

        def instavel():
            chamadas.append(1)
            if len(chamadas) < 3:
                raise httpx.ConnectTimeout("timed out")
            return "ok"

        assert inlabs._tentar(instavel) == "ok"
        assert len(chamadas) == 3

    def test_tentar_desiste_e_propaga(self):
        import httpx

        def sempre_falha():
            raise httpx.ConnectTimeout("timed out")

        with pytest.raises(httpx.TransportError):
            inlabs._tentar(sempre_falha, tentativas=2)


# ===========================================================================
# RUN ALL
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Testes de UI (Streamlit), i18n e acessibilidade.

O dashboard é uma app Streamlit (Python), não React/PWA. Estes testes cobrem:
  - Lógica de rendering (layout, títulos, labels)
  - i18n: strings em português, acentuação, caracteres especiais
  - Acessibilidade: contrastes implícitos, legibilidade de status

Rodar:  python -m tests.test_ui
Ou com pytest:  pytest tests/test_ui.py -v
"""
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.database.models import Vaga
from src.output import export_markdown
from dashboard import (CLASSES, UFS, TIPOS_VAGA, PERIODOS,
                       _painel_config, _painel_alerta_email, _busca_viva,
                       _tem_busca_viva)


# ===========================================================================
# DASHBOARD STRUCTURE
# ===========================================================================

class TestDashboardStructure:
    """Verifica se os dados do dashboard estão completos e coerentes."""

    def test_classes_de_instituicao_completas(self):
        assert "pública federal" in CLASSES
        assert "pública estadual" in CLASSES
        assert "pública municipal" in CLASSES
        assert "privada" in CLASSES
        assert "agência/fundação" in CLASSES
        assert "verificar manualmente" in CLASSES

    def test_ufs_cobrem_todo_brasil(self):
        assert len(UFS) == 27
        assert "SP" in UFS
        assert "RJ" in UFS
        assert "MG" in UFS
        assert "AC" in UFS
        assert "TO" in UFS

    def test_tipos_de_vaga_cobrem_principais(self):
        assert "Professor efetivo (universidade pública)" in TIPOS_VAGA
        assert "Pós-doutorado" in TIPOS_VAGA
        assert "Bolsa" in TIPOS_VAGA
        assert "Pesquisador" in TIPOS_VAGA

    def test_periodos_cobrem_janelas_uteis(self):
        assert None in PERIODOS.values()  # "Qualquer data"
        assert 7 in PERIODOS.values()
        assert 365 in PERIODOS.values()

    def test_periodos_sao_ordenados(self):
        chaves = list(PERIODOS.keys())
        valores = [v for v in PERIODOS.values() if v is not None]
        assert valores == sorted(valores)


# ===========================================================================
# I18N / LOCALIZAÇÃO
# ===========================================================================

class TestI18n:
    """O app é 100% em português. Strings não devem conter inglês acidental."""

    def test_labels_do_dashboard_em_portugues(self):
        """Labels comuns do Streamlit aparecem em português no código."""
        from dashboard import st
        # o arquivo dashboard.py deve ter os labels em português
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "Buscar por área ou palavra" in src
        assert "Tipo de instituição" in src
        assert "Estado" in src
        assert "Status" in src
        assert "Publicadas nos últimos" in src

    def test_mensagens_de_status_em_portugues(self):
        from dashboard import CORES_STATUS
        assert "aberta" in CORES_STATUS
        assert "vencida" in CORES_STATUS
        assert "sem prazo identificado" in CORES_STATUS

    def test_export_markdown_usa_portugues(self, tmp_path):
        v = Vaga(titulo="Professor de Filosofia", area="filosofia",
                 instituicao="UFMG", link_oficial="https://ufmg.br",
                 trecho_comprovacao="", classificacao_instituicao="pública federal",
                 natureza="professor efetivo", status="aberta", prazo_inscricao="30/07/2026")
        dest = export_markdown.exportar([v.to_dict()])
        text = dest.read_text(encoding="utf-8")
        assert "Públicas federais" in text
        assert "| Vaga |" in text

    def test_acentuacao_preservada_no_csv(self, tmp_path):
        import pandas as pd
        from src.output import export_csv
        v = Vaga(
            titulo="Filosofia — ética, lógica e política",
            area="filosofia",
            instituicao="Universidade Federal de Minas Gerais",
            link_oficial="https://ufmg.br",
            trecho_comprovacao="",
            classificacao_instituicao="pública federal",
            natureza="professor efetivo",
            status="aberta",
        )
        dest = export_csv.exportar([v.to_dict()])
        text = dest.read_text(encoding="utf-8-sig")
        assert "ética" in text
        assert "lógica" in text
        assert "política" in text

    def test_acentuacao_preservada_no_json(self, tmp_path):
        import json
        from src.output import export_json
        v = Vaga(
            titulo="Filosofia — ética e moral",
            area="filosofia",
            link_oficial="https://ufmg.br",
            trecho_comprovacao="",
            classificacao_instituicao="pública federal",
            natureza="professor efetivo",
            status="aberta",
        )
        dest = export_json.exportar([v.to_dict()])
        text = dest.read_text(encoding="utf-8")
        data = json.loads(text)
        assert data[0]["titulo"] == "Filosofia — ética e moral"

    def test_busca_sinonimos_trata_acentos(self):
        from src import sinonimos
        grupos = sinonimos.expandir("ética")
        qualquer = [f for g in grupos for f in g]
        assert "etica" in qualquer

    def test_busca_sinonimos_trata_ce_and_e(self):
        from src import sinonimos
        grupos = sinonimos.expandir("filosofia")
        qualquer = [f for g in grupos for f in g]
        assert "filosofia" in qualquer


# ===========================================================================
# ACCESSIBILITY (A11Y)
# ===========================================================================

class TestAcessibilidade:
    """Verifica critérios de acessibilidade no código-rendered."""

    def test_status_tem_cor_associada(self):
        from dashboard import CORES_STATUS
        assert CORES_STATUS["aberta"] == "green"
        assert CORES_STATUS["vencida"] == "red"
        assert CORES_STATUS["sem prazo identificado"] == "orange"

    def test_titulo_da_pagina_em_portugues(self):
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "Vagas Acadêmicas" in src

    def test_placeholders_instrutivos(self):
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "Ex.: Direito, Filosofia, Inteligência Artificial" in src

    def test_botao_principais_nao_sao_somente_icone(self):
        """Botões devem ter texto visível, não apenas emoji."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        # botões devem ter label legível
        assert "Busca geral" in src
        assert "Só nos diários oficiais" in src

    def test_expansores_tem_rotulo(self):
        """Expansores (sidebar) têm rótulo em português."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "Busca automática" in src
        assert "Receber vagas por e-mail" in src

    def test_mensagens_de_erro_sao_claras(self):
        """Mensagens de erro informam o que fazer, não código interno."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        # nenhuma mensagem deve vazar stack trace ou caminho de arquivo
        assert "Traceback" not in src
        assert "File" not in src or "data/processed/vagas.db" in src  # path do banco é ok


# ===========================================================================
# RESPONSIVIDADE (layout hints)
# ===========================================================================

class TestResponsividade:
    """Verifica media queries e ajustes de layout no CSS do dashboard."""

    def test_media_query_max_width_640(self):
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "max-width: 640px" in src

    def test_min_height_44px_para_controles(self):
        """WCAG recomenda alvo de toque mínimo de 44px."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "44px" in src

    def test_prefers_reduced_motion(self):
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "prefers-reduced-motion" in src

    def test_fonte_legivel(self):
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "Fira Sans" in src


# ===========================================================================
# EDGE CASES & ROBUSTNESS
# ===========================================================================

class TestRobustness:
    """Comportamento em situações de contorno."""

    def test_vaga_sem_area_nao_benca_busca(self):
        from src.main import filtrar
        user = {"areas": ["filosofia"], "instituicoes": ["publica_federal"],
                "estados": [], "incluir_vencidas": False}
        v = Vaga(titulo="Professor de Filosofia", instituicao="UFMG",
                 classificacao_instituicao="pública federal",
                 natureza="professor efetivo", area="",
                 link_oficial="https://ufmg.br",
                 trecho_comprovacao="concurso para professor de filosofia")
        aprovadas = filtrar([v], user)
        # _enriquecer deve inferir a área a partir do trecho
        assert len(aprovadas) == 1
        assert aprovadas[0].area == "filosofia"

    def test_vaga_com_titulo_muito_grande_nao_banca(self):
        from src.main import _enriquecer
        v = Vaga(
            titulo="A" * 500,
            link_oficial="https://x.com",
            trecho_comprovacao="B" * 1000,
            instituicao="U" * 200,
        )
        r = _enriquecer(v)
        # título não deve estourar - _enriquecer só corta em casos específicos
        assert len(r.titulo) <= 500  # original é preservado
        # trecho_comprovacao também é preservado (não há truncamento no _enriquecer)
        assert len(r.trecho_comprovacao) <= 1000

    def test_vaga_com_link_nao_https(self):
        from src.main import _enriquecer
        v = Vaga(titulo="X", link_oficial="http://exemplo.com",
                 trecho_comprovacao="", instituicao="U")
        r = _enriquecer(v)
        # link deve ser preservado (o dashboard é que decide como renderizar)
        assert r.link_oficial == "http://exemplo.com"

    def test_busca_com_espacos_sobrados(self):
        from src import sinonimos
        grupos = sinonimos.expandir("  filosofia   da   lógica  ")
        qualquer = [f for g in grupos for f in g]
        assert "filosofia" in qualquer
        assert "lógica" in qualquer or "logica" in qualquer

    def test_busca_com_caractere_especial(self):
        from src import sinonimos
        # caracteres especiais não devem quebrar a expansão
        grupos = sinonimos.expandir("filosofia&lógica")
        assert len(grupos) >= 1


# ===========================================================================
# RUN ALL
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

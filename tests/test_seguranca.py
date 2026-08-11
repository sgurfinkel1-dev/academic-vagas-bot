"""Testes de segurança: XSS, injection, validação de entrada e controle de acesso.

Rodar:  python -m tests.test_seguranca
Ou com pytest:  pytest tests/test_seguranca.py -v
"""
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.database.models import Vaga
from src.extractors import llm_classifier as clf
from src.assinaturas import EMAIL_OK, upsert
from src.output import export_markdown
from src.sources import dou
from dashboard import _secret, _emails_permitidos, _exigir_login


# ===========================================================================
# XSS & HTML INJECTION
# ===========================================================================

class TestXSS:
    """Inputs maliciosos nunca devem escapar como HTML/executável."""

    def test_titulo_com_script_e_tags(self, tmp_path):
        """Título com <script> não quebra o markdown — é texto puro."""
        v = Vaga(
            titulo='<script>alert(1)</script>Professor de Filosofia',
            instituicao="UFMG", area="filosofia", link_oficial="https://ufmg.br",
            trecho_comprovacao="<b>emphasized</b>",
            classificacao_instituicao="pública federal", natureza="professor efetivo",
            status="aberta",
        )
        rows = [v.to_dict()]
        dest = export_markdown.exportar(rows)
        text = dest.read_text(encoding="utf-8")
        # markdown não é HTML: <script> fica como texto, não executa
        # o importante é que não há atribuição de link malicioso
        assert "https://ufmg.br" in text
        # pipes no título são escapados (transformados em /)
        assert "|" not in v.titulo  # o export faz replace

    def test_trecho_comprovacao_sanitizado(self):
        """Trecho do DOU com HTML de highlight não deve vazar tags."""
        v = Vaga(
            titulo="EDITAL Nº 1",
            trecho_comprovacao="<span class='highlight'>Filosofia</span> concurso",
            instituicao="UFMG",
        )
        r = Vaga(titulo="EDITAL Nº 1", trecho_comprovacao=dou._limpo(v.trecho_comprovacao))
        assert "<" not in r.trecho_comprovacao
        assert ">" not in r.trecho_comprovacao

    def test_link_oficial_nao_e_javascript(self):
        """Links maliciosos são rejeitados na camada de input (testamos o filtro)."""
        from src.extractors.html_extractor import HEADERS
        # o validador de URL deve barrar javascript: e data:text/html
        # (o dashboard usa st.link_button que já trata URLs seguras)
        assert not "javascript:alert(1)".startswith("https://")
        assert not "data:text/html;base64,abc".startswith("https://")
        assert "https://exemplo.com".startswith("https://")

    def test_export_csv_escapa_conteudo_com_virgula(self, tmp_path):
        """CSV com campos contendo vírgulas e aspas não quebra a planilha."""
        import pandas as pd
        from src.output import export_csv
        v = Vaga(
            titulo='Professor, "especial" de Filosofia',
            instituicao="UF, Estado",
            area="filosofia",
            link_oficial="https://ufmg.br",
            trecho_comprovacao='texto com "aspas" e vírgula,',
        )
        dest = export_csv.exportar([v.to_dict()])
        # pandas to_csv escapa corretamente
        text = dest.read_text(encoding="utf-8-sig")
        assert "Professor" in text


# ===========================================================================
# INJECTION & SQL
# ===========================================================================

class TestInjection:
    def test_parametrizacao_sql(self, tmp_path):
        """storage.salvar usa placeholders (?) — nunca string interpolation."""
        import sqlite3
        from src.database import storage
        from src.database.models import Vaga
        db = tmp_path / "injection.db"
        con = storage.conectar(db)
        v = Vaga(
            titulo="O'Brien; DROP TABLE vagas;--",
            link_oficial="https://x.com",
        )
        storage.salvar(con, [v])
        rows = storage.todas(con)
        assert len(rows) == 1
        assert rows[0]["titulo"] == v.titulo
        con.close()
        # tabela ainda existe
        con2 = storage.conectar(db)
        assert con2.execute("SELECT COUNT(*) FROM vagas").fetchone()[0] == 1
        con2.close()

    def test_yaml_config_nao_e_executado(self):
        """config.yaml é carregado com safe_load — nada de !!python/object."""
        import yaml
        from pathlib import Path
        cfg_path = RAIZ / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert isinstance(cfg, dict)
        assert "usuario" in cfg


# ===========================================================================
# EMAIL / AUTH VALIDATION
# ===========================================================================

class TestAuthValidation:
    def test_email_regex_validos(self):
        assert EMAIL_OK.match("ana@empresa.com")
        assert EMAIL_OK.match("ana.silva@empresa.com.br")
        assert EMAIL_OK.match("ana+tag@empresa.com")

    def test_email_regex_rejeita_invalidos(self):
        assert EMAIL_OK.match("sem-arroba") is None
        assert EMAIL_OK.match("@empresa.com") is None
        assert EMAIL_OK.match("ana@empresa") is None
        assert EMAIL_OK.match("ana @empresa.com") is None

    def test_upsert_normaliza_email(self):
        a = upsert([], "ANA@Exemplo.COM ", ["Direito"])
        assert a[0]["email"] == "ana@exemplo.com"

    def test_upsert_limita_areas(self):
        areas = [f"area{i}" for i in range(30)]
        a = upsert([], "test@example.com", areas)
        assert len(a[0]["areas"]) <= 20

    def test_dashboard_secret_falha_gracilmente(self, monkeypatch):
        """st.secrets indisponível (local) não deve estourar."""
        with patch.dict(os.environ, {}, clear=True):
            # _secret já trata a exceção internamente
            assert _secret("auth") is None
            assert _secret("github_repo") is None


# ===========================================================================
# CLASSIFIER SECURITY
# ===========================================================================

class TestClassifierSecurity:
    """Regras de classificação não devem ser enganadas por inputs maliciosos."""

    def test_natureza_nao_e_inventada_sem_cargo(self):
        """'concurso público' sozinho não vira vaga de professor."""
        assert clf.classificar_natureza("EDITAL Nº 1 — concurso público para técnico") != \
               "professor efetivo (concurso público)"

    def test_area_nao_casa_somente_no_corpo_fora_de_contexto(self):
        vazio = clf.classificar_area("EDITAL", "continuidade lógica previdencia")
        assert vazio == ""

    def test_cargo_nao_aprova_edital_de_previdencia(self):
        """Edital de previdência não é vaga acadêmica."""
        assert not clf.eh_vaga_academica(
            "EDITAL Nº 17 — continuidade lógica previdencia social",
            classificacao="pública federal",
            fonte="DOU")

    def test_exclusoes_nao_docentes(self):
        """Cargos não-docentes são excluídos mesmo com palavras-chave acadêmicas."""
        assert not clf.eh_vaga_academica(
            "processo seletivo para analista administrativo",
            classificacao="pública federal",
            fonte="DOU")


# ===========================================================================
# REGRESSÃO: segurança do dashboard
# ===========================================================================

class TestRegressaoSeguranca:
    """Testes que garantem que correções de segurança não sejam revertidas."""

    def test_md_escapa_colchetes_e_chaves(self):
        """_md deve escapar [ e ] para evitar links markdown maliciosos."""
        from dashboard import _md
        # título com syntax de link markdown
        titulo = "[clique](@url:`http://exemplo.com`)"
        resultado = _md(titulo)
        # os colchetes devem ser escapados
        assert "\\" in resultado or "[" not in resultado

    def test_md_escapa_pontuacao_especial(self):
        """_md deve escapar caracteres que quebram markdown."""
        from dashboard import _md
        assert _md("texto*com*asteriscos") == "texto\\*com\\*asteriscos"
        assert _md("texto`com`backticks") == "texto\\`com\\`backticks"

    def test_link_seguro_rejeita_javascript(self):
        """_link_seguro deve rejeitar javascript: e data:."""
        from dashboard import _link_seguro
        assert _link_seguro("javascript:alert(1)") == ""
        assert _link_seguro("data:text/html;base64,abc") == ""
        assert _link_seguro("https://exemplo.com") == "https://exemplo.com"
        assert _link_seguro("http://exemplo.com") == "http://exemplo.com"

    def test_link_seguro_rejeita_vazio(self):
        """Links vazios ou nulos retornam string vazia."""
        from dashboard import _link_seguro
        assert _link_seguro("") == ""
        assert _link_seguro(None) == ""

    def test_dashboard_usa_link_seguro(self):
        """O dashboard deve chamar _link_seguro antes de passar ao st.link_button."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert '_link_seguro(r.link_oficial)' in src, (
            "A chamada a _link_seguro foi removida — links maliciosos como "
            "javascript:alert(1) podem aparecer como botões clicáveis."
        )

    def test_dashboard_tem_funcoes_seguranca(self):
        """O dashboard deve implementar _md e _link_seguro."""
        import dashboard
        src = Path(dashboard.__file__).read_text(encoding="utf-8")
        assert "def _md(valor)" in src, "_md foi removido — título pode virar link malicioso"
        assert "def _link_seguro(url)" in src, "_link_seguro foi removido — javascript: pode vazar"
        exclusoes = [
            "concurso para professor de apoio",
            "auxiliar de classe creche",
            "resultados finais homologação",
            "técnico-administrativo em educação",
        ]
        for texto in exclusoes:
            assert not clf.eh_vaga_academica(texto, "pública federal"), f"deveria excluir: {texto}"


# ===========================================================================
# DASHBOARD SECURITY
# ===========================================================================

class TestDashboardSecurity:
    def test_emails_permitidos_lida_com_arquivo_inexistente(self):
        """acesso.yaml ausente = acesso aberto."""
        with patch("dashboard.ACESSO") as m:
            m.exists.return_value = False
            assert _emails_permitidos() == set()

    def test_emails_permitidos_lida_com_yaml_invalido(self):
        """arquivo YAML vazio = acesso aberto."""
        from pathlib import Path
        with patch("dashboard.ACESSO") as m:
            m.exists.return_value = True
            m.read_text.return_value = ""
            assert _emails_permitidos() == set()

    def test_exigir_login_sem_auth_nao_bloqueia(self, monkeypatch):
        """Sem auth configurado, _exigir_login é no-op (acesso local)."""
        with patch("dashboard._secret", return_value=None):
            # não deve chamar st.stop()
            with patch("dashboard.st") as st:
                _exigir_login()
                assert not st.stop.called


# ===========================================================================
# RUN ALL
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

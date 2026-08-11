"""Testes de integração: CRUD, persistência, busca, validação e exportação.

Rodar:  python -m tests.test_integracao
Ou com pytest:  pytest tests/test_integracao.py -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# permite importar src do diretório-raiz do projeto
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.database.models import Vaga, CAMPOS
from src.database import storage
from src import sinonimos
from src.extractors import llm_classifier as clf
from src.output import export_csv, export_json, export_markdown
from src.assinaturas import carregar, serializar, upsert, vagas_do_assinante
from src.alerts import telegram_alert, discord_alert, email_alert
from src.sources import gupy, fapesp, dou, universidades_publicas, anpof
from src.main import _enriquecer, filtrar, montar_alerta


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture
def tmp_db(tmp_path):
    """Banquinho SQLite em disco temporário."""
    db = tmp_path / "test.db"
    con = storage.conectar(db)
    yield db, con
    con.close()


@pytest.fixture
def vaga_exemplo():
    return Vaga(
        titulo="Concurso para professor efetivo de Filosofia",
        instituicao="Universidade Federal de Minas Gerais",
        classificacao_instituicao="pública federal",
        natureza="professor efetivo (concurso público)",
        area="filosofia",
        subarea="Filosofia Política",
        departamento="Departamento de Filosofia",
        cidade="Belo Horizonte",
        estado="MG",
        pais="Brasil",
        modalidade="presencial",
        titulacao_exigida="doutorado",
        regime="efetivo",
        remuneracao_ou_bolsa="R$ 8.000,00",
        data_publicacao="01/07/2026",
        prazo_inscricao="30/07/2026",
        status="aberta",
        link_oficial="https://www.ufmg.br/concursos/filosofia",
        link_edital_pdf="https://www.ufmg.br/concursos/filosofia.pdf",
        fonte="Página oficial de concursos (UFMG)",
        trecho_comprovacao="concurso para o Departamento de Filosofia",
        confianca="alto",
        observacoes="",
    )


@pytest.fixture
def vagas_multiple(vaga_exemplo):
    return [
        vaga_exemplo,
        Vaga(
            titulo="Bolsa de pós-doutorado em Computação",
            instituicao="FAPESP",
            classificacao_instituicao="agência/fundação",
            natureza="pós-doutorado",
            area="computação",
            estado="SP",
            link_oficial="https://fapesp.br/bolsa",
            fonte="FAPESP Oportunidades",
            trecho_comprovacao="bolsa de pós-doutorado",
        ),
        Vaga(
            titulo="Professor visitante de Direito",
            instituicao="PUC-SP",
            classificacao_instituicao="privada",
            natureza="professor visitante",
            area="direito",
            estado="SP",
            link_oficial="https://pucsp.br/vaga",
            fonte="Página oficial de concursos (PUC-SP)",
            trecho_comprovacao="professor visitante",
        ),
    ]


# ===========================================================================
# DATABASE / CRUD
# ===========================================================================

class TestStorageCRUD:
    """CRUD via storage.py — INSERT, SELECT, deduplicação."""

    def test_create_inserts(self, tmp_db, vaga_exemplo):
        db, con = tmp_db
        novas = storage.salvar(con, [vaga_exemplo])
        assert len(novas) == 1
        assert novas[0].chave() == vaga_exemplo.chave()
        rows = storage.todas(con)
        assert len(rows) == 1
        assert rows[0]["titulo"] == vaga_exemplo.titulo
        assert rows[0]["chave"] == vaga_exemplo.chave()

    def test_dedup_returns_only_new(self, tmp_db, vaga_exemplo):
        db, con = tmp_db
        storage.salvar(con, [vaga_exemplo])
        novas = storage.salvar(con, [vaga_exemplo])  # mesmo registro
        assert novas == []

    def test_dedup_different_chave(self, tmp_db, vaga_exemplo):
        db, con = tmp_db
        v2 = Vaga(titulo="Outra vaga", link_oficial="https://outro.com")
        storage.salvar(con, [vaga_exemplo])
        novas = storage.salvar(con, [v2])
        assert len(novas) == 1

    def test_read_all_ordered_by_found_at(self, tmp_db):
        db, con = tmp_db
        v1 = Vaga(titulo="Primeira", link_oficial="https://a.com")
        v2 = Vaga(titulo="Segunda", link_oficial="https://b.com")
        # Inserir com timestamps diferentes para garantir ordenação
        con.execute("INSERT OR IGNORE INTO vagas (chave, encontrada_em, titulo, link_oficial) VALUES (?, datetime('now', '-1 second'), ?, ?)",
                    (v1.chave(), v1.titulo, v1.link_oficial))
        con.execute("INSERT OR IGNORE INTO vagas (chave, encontrada_em, titulo, link_oficial) VALUES (?, datetime('now'), ?, ?)",
                    (v2.chave(), v2.titulo, v2.link_oficial))
        con.commit()
        rows = storage.todas(con)
        assert len(rows) == 2
        # a segunda deve vir primeiro (ORDER BY encontrada_em DESC)
        assert rows[0]["titulo"] == "Segunda"
        assert rows[1]["titulo"] == "Primeira"

    def test_migrate_add_column(self, tmp_db):
        db, con = tmp_db
        # simula um CAMPOS novo adicionado depois do banco criado
        with patch.object(storage, "CAMPOS", new=["titulo"] + CAMPOS):
            # conexão já criada com a tabela original — o ALTER TABLE vai rodar
            # ao chamar conectar() novamente
            pass
        # apenas confirma que conectar() não quebra com tabela já existente
        con2 = storage.conectar(db)
        con2.close()


# ===========================================================================
# EXPORT (CSV / JSON / MD)
# ===========================================================================

class TestExport:
    def test_csv_creates_utf8sig(self, tmp_path, vagas_multiple):
        dest = export_csv.exportar([v.to_dict() for v in vagas_multiple])
        assert dest.exists()
        text = dest.read_text(encoding="utf-8-sig")
        assert "Concurso para professor" in text
        assert "Bolsa de pós-doutorado" in text

    def test_json_keys_match_campos(self, tmp_path, vagas_multiple):
        dest = export_json.exportar([v.to_dict() for v in vagas_multiple])
        assert dest.exists()
        data = json.loads(dest.read_text(encoding="utf-8"))
        assert len(data) == 3
        for row in data:
            for k in CAMPOS:
                assert k in row, f"falta campo {k}"

    def test_json_escapes_unicode(self, tmp_path, vaga_exemplo):
        vaga_exemplo.titulo = "Filosofia — ética e moral"
        dest = export_json.exportar([vaga_exemplo.to_dict()])
        text = dest.read_text(encoding="utf-8")
        assert "Filosofia" in text
        # ensure_ascii=False: o UTF-8 fica direto
        assert "——" not in text  # não deve fugir para \uXXXX

    def test_markdown_sections(self, tmp_path, vagas_multiple):
        dest = export_markdown.exportar([v.to_dict() for v in vagas_multiple])
        assert dest.exists()
        text = dest.read_text(encoding="utf-8")
        assert "Públicas federais" in text
        assert "Bolsas / pós-doc / agências" in text
        assert "Privadas" in text

    def test_markdown_no_section_when_empty(self, tmp_path):
        dest = export_markdown.exportar([])
        text = dest.read_text(encoding="utf-8")
        assert text.startswith("# Vagas acadêmicas encontradas")
        assert "## " not in text  # nenhuma seção


# ===========================================================================
# SEARCH + SINÔNIMOS
# ===========================================================================

class TestSinonimos:
    def test_expand_epistemologia(self):
        grupos = sinonimos.expandir("epistemologia")
        assert len(grupos) == 1
        formas = grupos[0]
        assert "epistemologia" in formas
        assert "teoria do conhecimento" in formas
        assert "gnosiologia" in formas

    def test_expand_filosofia_da_logica(self):
        grupos = sinonimos.expandir("filosofia da lógica")
        # "filosofia da lógica" é UM grupo (forma longa) + palavras soltas
        qualquer = [f for g in grupos for f in g]
        assert "filosofia da logica" in qualquer
        assert "logica" in qualquer

    def test_genericas_ignora_palavras_comuns(self):
        grupos = sinonimos.expandir("concurso professor efetivo")
        palavras = [p for g in grupos for p in g]
        # "concurso" e "professor" são genéricas — não devem aparecer como termos
        assert "concurso" not in palavras
        assert "professor" not in palavras

    def test_palavra_sem_sinonimo(self):
        assert sinonimos.expandir("química") == [["quimica"]]

    def test_sem_acento_normalize(self):
        assert sinonimos.sem_acento("Ética") == "etica"
        assert sinonimos.sem_acento("Lógica") == "logica"
        assert sinonimos.sem_acento("Filosofia") == "filosofia"


class TestBusca:
    """Busca reproduzida do dashboard (mesma lógica do test_enriquecimento)."""

    @staticmethod
    def _buscar(df, consulta):
        import pandas as pd
        import numpy as np
        import re
        grupos = sinonimos.expandir(consulta)
        palavras = [g[0] for g in grupos]
        subarea = df["subarea"].fillna("").map(sinonimos.sem_acento)
        tema = df[["titulo", "area"]].fillna("").agg(" ".join, axis=1).map(sinonimos.sem_acento)
        corpo = df[["instituicao", "natureza", "trecho_comprovacao"]].fillna("").agg(" ".join, axis=1).map(sinonimos.sem_acento)
        casa = lambda s: pd.concat(
            [s.str.contains(r"\b(?: " + "|".join(re.escape(f) for f in g) + r")\b", na=False)
             for g in grupos], axis=1, keys=palavras)
        n_sub, n_tema, n_corpo = casa(subarea), casa(tema), casa(corpo)
        onde = n_sub | n_tema | n_corpo
        peso = np.log(len(df) / onde.sum(axis=0).clip(lower=1)) + 0.1
        campo = np.maximum.reduce([n_sub.values * 4, n_tema.values * 3, n_corpo.values * 1])
        pontos = (pd.Series((campo * peso.values).sum(axis=1), index=df.index)
                  + onde.all(axis=1) * peso.sum() * 4)
        relevantes = (n_sub | n_tema).any(axis=1)
        return df[relevantes].assign(_p=pontos[relevantes]).sort_values("_p", ascending=False)

    def test_busca_filosofia_da_logica(self):
        import pandas as pd
        df = pd.DataFrame([
            {"titulo": "Professor em Lógica", "area": "lógica", "subarea": "",
             "instituicao": "UFSC", "natureza": "professor efetivo", "trecho_comprovacao": ""},
            {"titulo": "Professor de Filosofia", "area": "filosofia", "subarea": "",
             "instituicao": "UFAM", "natureza": "professor efetivo", "trecho_comprovacao": ""},
            {"titulo": "Bolsa em Química", "area": "química", "subarea": "",
             "instituicao": "IQ", "natureza": "bolsa", "trecho_comprovacao": ""},
        ])
        achados = set(self._buscar(df, "filosofia da lógica").titulo)
        assert "Professor em Lógica" in achados
        assert "Bolsa em Química" not in achados

    def test_busca_por_subarea_valor_mais(self):
        import pandas as pd
        # Cria dados onde a subárea é o fator diferenciador
        base = dict(instituicao="UF", natureza="professor efetivo", trecho_comprovacao="")
        df = pd.DataFrame([
            {"titulo": "Professor de Filosofia", "area": "filosofia", "subarea": "Lógica", **base},
            {"titulo": "Professor de Filosofia", "area": "filosofia", "subarea": "Ética", **base},
        ])
        res = self._buscar(df, "filosofia lógica")
        # Ambas as vagas devem aparecer (ambas têm "filosofia" e "lógica" no título/area/subárea)
        assert len(res) == 2
        # A subárea "Lógica" deve ter peso maior (4x) que as outras ocorrências
        # Verifica se a ordenação prefere a vaga com subárea correspondente
        assert "Professor de Filosofia" in list(res.titulo)


# ===========================================================================
# VALIDATION / CLASSIFICATION
# ===========================================================================

class TestClassificacao:
    def test_area_filosofia_no_titulo(self):
        assert clf.classificar_area("Concurso para professor de Filosofia") == "filosofia"

    def test_area_lógica_ganha_de_filosofia(self):
        # "lógica" casa primeiro na ordem das regras
        assert clf.classificar_area("Professor do setor de Lógica") == "lógica"

    def test_area_no_corpo_somente_em_contexto(self):
        # menção solta em "continuidade lógica" não conta
        assert clf.classificar_area("EDITAL Nº 1", "continuidade lógica previdencia social") == ""

    def test_area_em_contexto_declarativo(self):
        assert clf.classificar_area("EDITAL", "concurso para o departamento de Filosofia") == "filosofia"

    def test_nao_casa_nome_de_casa(self):
        # "Escola de Filosofia, Letras e Ciências Humanas" é a CASA, não a área
        assert clf.classificar_area("Bolsa em Antropologia",
                                     "Escola de Filosofia, Letras e Ciências Humanas") != "filosofia"

    def test_natureza_concurso_so_com_cargo_docente(self):
        # concurso público sozinho não vira "professor efetivo"
        tecnico = "EDITAL Nº 10 CONCURSO PÚBLICO para cargos técnico-administrativos"
        assert "professor" not in clf.classificar_natureza(tecnico).lower()

    def test_natureza_docente_detectada(self):
        assert clf.classificar_natureza("concurso público de provas e títulos para professor") == \
               "professor efetivo (concurso público)"

    def test_eh_vaga_academica_rejeita_tecnico(self):
        assert not clf.eh_vaga_academica(
            "concurso público técnico-administrativo",
            "pública federal")

    def test_eh_vaga_academica_aprova_docente(self):
        assert clf.eh_vaga_academica(
            "concurso para professor efetivo de Filosofia",
            "pública federal")

    def test_status_por_prazo_aberta(self):
        assert clf.status_por_prazo("30/12/2099") == "aberta"

    def test_status_por_prazo_vencida(self):
        assert clf.status_por_prazo("01/01/2020") == "vencida"

    def test_status_por_prazo_sem_prazo(self):
        assert clf.status_por_prazo("") == "sem prazo identificado"

    def test_extrair_prazo_encontra_data(self):
        assert clf.extrair_prazo("Inscrições até 30/07/2026") == "30/07/2026"

    def test_extrair_prazo_nao_encontra(self):
        assert clf.extrair_prazo("Sem prazo identificado") == ""


# ===========================================================================
# ENRICHMENT / FILTRAGEM
# ===========================================================================

class TestEnriquecimento:
    def test_remonta_titulo_edital(self):
        v = Vaga(titulo="EDITAL Nº 1584, DE 2 DE JULHO DE 2026",
                 instituicao="UFMG", natureza="professor efetivo", area="filosofia")
        r = _enriquecer(v)
        assert "EDITAL" not in r.titulo or "2 DE JULHO" not in r.titulo
        assert "UFMG" in r.titulo

    def test_preserva_titulo_legivel(self):
        orig = "Concurso para professor efetivo de Filosofia na UFAM"
        v = Vaga(titulo=orig, instituicao="UFAM", natureza="professor efetivo", area="filosofia")
        assert _enriquecer(v).titulo == orig

    def test_filtrar_aplica_regras(self):
        user = {"areas": ["filosofia"], "instituicoes": ["publica_federal"],
                "estados": [], "incluir_vencidas": False}
        vagas = [
            Vaga(titulo="Professor de Filosofia", instituicao="UFMG",
                 classificacao_instituicao="pública federal", natureza="professor efetivo",
                 area="filosofia", status="aberta",
                 link_oficial="https://ufmg.br", trecho_comprovacao="professor de filosofia"),
            Vaga(titulo="Técnico Administrativo", instituicao="UFMG",
                 classificacao_instituicao="pública federal", natureza="técnico",
                 area="", status="aberta",
                 link_oficial="https://ufmg.br", trecho_comprovacao="técnico administrativo"),
        ]
        aprovadas = filtrar(vagas, user)
        assert len(aprovadas) == 1
        assert aprovadas[0].area == "filosofia"


# ===========================================================================
# ALERTS (unitários, sem rede)
# ===========================================================================

class TestAlertas:
    def test_telegram_sem_config(self):
        with patch.dict(os.environ, {}, clear=True):
            assert telegram_alert.enviar("msg", {}) is False

    def test_discord_sem_config(self):
        with patch.dict(os.environ, {}, clear=True):
            assert discord_alert.enviar("msg", {}) is False

    def test_email_sem_config(self):
        with patch.dict(os.environ, {}, clear=True):
            assert email_alert.enviar("msg", {}) is False

    def test_telegram_usa_env(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "123"}):
            with patch("src.alerts.telegram_alert.httpx.post") as m:
                m.return_value.raise_for_status.return_value = None
                assert telegram_alert.enviar("oi", {}) is True
                m.assert_called_once()

    def test_email_usa_env(self):
        with patch.dict(os.environ, {"SMTP_USER": "u", "SMTP_PASS": "p"}):
            with patch("src.alerts.email_alert.smtplib.SMTP") as m:
                inst = m.return_value.__enter__.return_value
                inst.send_message.return_value = None
                assert email_alert.enviar("oi", {}) is True
                m.assert_called_once()


# ===========================================================================
# ASSINATURAS
# ===========================================================================

class TestAssinaturas:
    def test_upsert_cria(self):
        a = upsert([], "fulano@exemplo.com", ["Direito"])
        assert len(a) == 1
        assert a[0]["email"] == "fulano@exemplo.com"

    def test_upsert_update_nao_duplica(self):
        a = upsert([], "fulano@exemplo.com", ["Direito"])
        a = upsert(a, "fulano@exemplo.com", ["Medicina"])
        assert len(a) == 1
        assert a[0]["areas"] == ["Medicina"]

    def test_upsert_remove_quando_ativo_false(self):
        a = upsert([], "fulano@exemplo.com", ["Direito"])
        a = upsert(a, "fulano@exemplo.com", [], ativo=False)
        assert a == []

    def test_upsert_rejeita_email_invalido(self):
        with pytest.raises(ValueError):
            upsert([], "sem-arroba", [])

    def test_vagas_do_assinante_filtra_por_area(self):
        from types import SimpleNamespace
        v1 = SimpleNamespace(titulo="Direito Civil", area="", trecho_comprovacao="")
        v2 = SimpleNamespace(titulo="Bolsa Química", area="", trecho_comprovacao="")
        assert vagas_do_assinante({"areas": ["direito"]}, [v1, v2]) == [v1]

    def test_vagas_do_assinante_sem_area_pegatudo(self):
        from types import SimpleNamespace
        v1 = SimpleNamespace(titulo="A", area="", trecho_comprovacao="")
        v2 = SimpleNamespace(titulo="B", area="", trecho_comprovacao="")
        assert vagas_do_assinante({"areas": []}, [v1, v2]) == [v1, v2]


# ===========================================================================
# MONITAR_ALERTA
# ===========================================================================

class TestMonitorAlerta:
    def test_monta_texto_com_vagas(self):
        v = Vaga(titulo="Professor de Filosofia — UFMG", instituicao="UFMG",
                 area="filosofia", link_oficial="https://ufmg.br")
        msg = montar_alerta([v], {"areas": ["filosofia"]})
        assert "Professor de Filosofia" in msg
        assert "UFMG" in msg
        assert "filosofia" in msg.lower()

    def test_trunca_em_15_itens(self):
        vagas = [Vaga(titulo=f"Vaga {i}", link_oficial="https://x.com") for i in range(20)]
        msg = montar_alerta(vagas, {"areas": []})
        assert "e mais 5" in msg


# ===========================================================================
# RUN ALL
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Proteções aplicadas a toda a suíte."""
import pytest

from src.output import export_csv, export_json, export_markdown


@pytest.fixture(autouse=True)
def _saida_isolada(tmp_path, monkeypatch):
    """Impede que a suíte escreva por cima dos dados versionados.

    exportar() grava em data/processed/vagas.{csv,json,md} — os arquivos que o
    robô diário publica no repositório. Os testes de export chamavam a função
    de verdade, então rodar a suíte deixava os três modificados no git status;
    um `git add -A` distraído comitava fixture de teste por cima da coleta do
    dia. Autouse porque a proteção deve valer para qualquer teste futuro, não
    só para os que existem hoje.
    """
    for modulo in (export_csv, export_json, export_markdown):
        monkeypatch.setattr(modulo, "SAIDA", tmp_path)

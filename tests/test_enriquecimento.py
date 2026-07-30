"""Checa área inferida, título remontado do DOU e o parser da ANPOF.
Rodar: python -m tests.test_enriquecimento (não precisa de rede exceto o teste da ANPOF).
"""
from src.database.models import Vaga
from src.extractors import llm_classifier as clf
from src.main import _enriquecer


def test_area():
    casos = [
        ("Concurso para professor de Filosofia Medieval", "filosofia"),
        ("Professor do setor de estudo Lógica", "lógica"),  # lógica vem antes de filosofia
        ("Edital para docente de Direito Penal", "direito"),
        ("Professor de Engenharia de Software", "computação"),  # mais específico que engenharia
        ("EDITAL Nº 1584, DE 2 DE JULHO DE 2026", ""),  # nada a inferir: melhor vazio que errado
    ]
    for texto, esperado in casos:
        obtido = clf.classificar_area(texto)
        assert obtido == esperado, f"{texto!r}: esperava {esperado!r}, veio {obtido!r}"
    print("OK  área")


def test_titulo_dou():
    v = _enriquecer(Vaga(
        titulo="EDITAL Nº 1584, DE 2 DE JULHO DE 2026",
        instituicao="Universidade Federal de Minas Gerais",
        natureza="professor efetivo (concurso público)",
        trecho_comprovacao="concurso para o departamento de Filosofia"))
    assert v.area == "filosofia", v.area
    assert "Filosofia" in v.titulo or "filosofia" in v.titulo, v.titulo
    assert "Minas Gerais" in v.titulo, v.titulo
    assert "DE 2 DE JULHO" not in v.titulo, "a data do ato devia sair do título"
    print("OK  título DOU ->", v.titulo)

    # título que já é legível não pode ser reescrito
    orig = "Concurso para professor efetivo de Filosofia na UFAM"
    assert _enriquecer(Vaga(titulo=orig, instituicao="UFAM")).titulo == orig
    print("OK  título legível preservado")


def test_anpof():
    from src.sources import anpof
    vagas = anpof.buscar(dias=365)
    assert len(vagas) >= 10, f"esperava >=10 itens no ano, veio {len(vagas)}"
    docentes = [v for v in vagas
                if clf.eh_vaga_academica(f"{v.titulo} {v.natureza} {v.trecho_comprovacao}",
                                         v.classificacao_instituicao)]
    assert len(docentes) >= 5, f"esperava >=5 vagas docentes, veio {len(docentes)}"
    assert all(v.link_oficial.startswith("https://anpof.org.br/") for v in vagas)
    assert all(v.area for v in vagas), "toda vaga da ANPOF tem área (filosofia por padrão)"
    print(f"OK  ANPOF ({len(vagas)} itens, {len(docentes)} vagas docentes)")


if __name__ == "__main__":
    test_area()
    test_titulo_dou()
    test_anpof()
    print("todos passaram")

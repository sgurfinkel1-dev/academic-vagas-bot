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
    print("OK  área pelo título")


def test_area_no_corpo():
    """No corpo do edital a palavra só conta onde o edital declara a área da vaga."""
    ruido = [  # casos reais que estavam entrando como vaga de lógica
        "diante da continuidade lógica previdencia social (mps)",
        "matematica discreta e lógica de cargos de professor",
        "deveria ser apresentado a) com argumentacao lógica",
    ]
    for corpo in ruido:
        assert clf.classificar_area("EDITAL Nº 17", corpo) == "", corpo

    declara = [("concurso para o Departamento de Filosofia da UFMG", "filosofia"),
               ("vagas para o setor de estudo: Filosofia Africana", "filosofia"),
               ("provimento na área de Direito Processual", "direito")]
    for corpo, esperado in declara:
        assert clf.classificar_area("EDITAL Nº 1", corpo) == esperado, corpo

    # nome da instituição não é área: a bolsa é de antropologia, não de filosofia
    area = clf.classificar_area("Bolsa de PD em Antropologia Forense",
                                "Escola de Filosofia, Letras e Ciências Humanas")
    assert area != "filosofia", area
    print("OK  área pelo corpo (só em contexto de declaração)")


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


def _buscar(df, consulta):
    """Reproduz a busca por texto do dashboard (mesma regra, para poder checá-la aqui)."""
    import re
    import unicodedata
    import pandas as pd
    import numpy as np
    from src import sinonimos
    sa = sinonimos.sem_acento
    grupos = sinonimos.expandir(consulta)
    palavras = [g[0] for g in grupos]
    subarea = df["subarea"].fillna("").map(sa) if "subarea" in df else pd.Series("", index=df.index)
    tema = df[["titulo", "area"]].fillna("").agg(" ".join, axis=1).map(sa)
    corpo = df[["instituicao", "natureza", "trecho_comprovacao"]].fillna("").agg(" ".join, axis=1).map(sa)
    casa = lambda s: pd.concat(
        [s.str.contains(r"\b(?:" + "|".join(re.escape(f) for f in g) + r")\b", na=False)
         for g in grupos], axis=1, keys=palavras)
    n_sub, n_tema, n_corpo = casa(subarea), casa(tema), casa(corpo)
    onde = n_sub | n_tema | n_corpo
    peso = np.log(len(df) / onde.sum(axis=0).clip(lower=1)) + 0.1
    campo = np.maximum.reduce([n_sub.values * 4, n_tema.values * 3, n_corpo.values * 1])
    pontos = (pd.Series((campo * peso.values).sum(axis=1), index=df.index)
              + onde.all(axis=1) * peso.sum() * 4)
    rel = (n_sub | n_tema).any(axis=1)
    return df[rel].assign(_p=pontos[rel]).sort_values("_p", ascending=False)


def test_busca_relevante():
    """'filosofia da lógica' não pode trazer vaga de química/antropologia."""
    import pandas as pd
    df = pd.DataFrame([
        # o que TEM que aparecer
        {"titulo": "Concurso para professor efetivo de Filosofia", "area": "filosofia",
         "instituicao": "UFAM", "natureza": "professor efetivo", "trecho_comprovacao": ""},
        {"titulo": "Professor do setor de estudo Lógica", "area": "lógica",
         "instituicao": "UFSC", "natureza": "professor efetivo", "trecho_comprovacao": ""},
        # o que NÃO pode aparecer
        {"titulo": "Bolsa de PD em Antropologia Forense", "area": "sociologia/antropologia",
         "instituicao": "Escola de Filosofia, Letras e Ciências Humanas",
         "natureza": "bolsa", "trecho_comprovacao": "", "subarea": ""},
        {"titulo": "Bolsa de PD em Química", "area": "química",
         "instituicao": "Instituto de Química", "natureza": "bolsa", "trecho_comprovacao": ""},
        {"titulo": "EDITAL MPS Nº 17", "area": "", "instituicao": "Previdência",
         "natureza": "não informado", "trecho_comprovacao": "continuidade lógica previdencia"},
    ])
    achados = set(_buscar(df, "filosofia da lógica").titulo)
    # "filosofia da lógica" é UM conceito (grupo de sinônimos), não duas palavras soltas:
    # traz a vaga de lógica, não filosofia em geral. Quem quer o amplo busca "filosofia".
    assert "Professor do setor de estudo Lógica" in achados, achados
    for lixo in ["Bolsa de PD em Antropologia Forense", "Bolsa de PD em Química", "EDITAL MPS Nº 17"]:
        assert lixo not in achados, f"{lixo!r} não devia aparecer em 'filosofia da lógica'"

    amplo = set(_buscar(df, "filosofia").titulo)
    assert "Concurso para professor efetivo de Filosofia" in amplo, amplo
    assert "Bolsa de PD em Antropologia Forense" not in amplo, "FFLCH não é área"

    # busca de uma palavra só continua funcionando
    assert "Bolsa de PD em Química" in set(_buscar(df, "química").titulo)
    print(f"OK  busca relevante ({len(achados)} vagas para 'filosofia da lógica', sem lixo)")


def test_sinonimos():
    """Quem busca 'epistemologia' também quer 'teoria do conhecimento', e vice-versa."""
    import pandas as pd
    from src import sinonimos
    base = dict(instituicao="UF", natureza="professor efetivo", trecho_comprovacao="")
    df = pd.DataFrame([
        {"titulo": "Professor efetivo", "area": "filosofia",
         "subarea": "Teoria do Conhecimento", **base},
        {"titulo": "Professor efetivo", "area": "filosofia", "subarea": "Ética", **base},
        {"titulo": "Professor efetivo", "area": "química", "subarea": "", **base},
    ])
    assert list(_buscar(df, "epistemologia").index) == [0], "sinônimo de epistemologia falhou"
    assert list(_buscar(df, "gnosiologia").index) == [0]
    assert list(_buscar(df, "filosofia moral").index) == [1], "ética = filosofia moral"

    # o grupo inteiro conta como UM termo, não como vários
    assert len(sinonimos.expandir("epistemologia")) == 1
    # palavra sem sinônimo cadastrado continua valendo por si
    assert sinonimos.expandir("química") == [["quimica"]]
    print("OK  sinônimos de subárea")


def test_ordena_por_especificidade():
    """O termo raro manda: em 'filosofia da lógica' quase tudo casa 'filosofia',
    então quem decide a ordem é 'lógica'. E a subárea declarada vale mais que o título."""
    import pandas as pd
    base = dict(instituicao="UF", natureza="professor efetivo", trecho_comprovacao="")
    df = pd.DataFrame([
        {"titulo": "Professor efetivo em lógica", "area": "lógica", "subarea": "", **base},
        {"titulo": "Professor efetivo em filosofia", "area": "filosofia",
         "subarea": "Ensino de Filosofia", **base},
        {"titulo": "Professor efetivo em filosofia", "area": "filosofia",
         "subarea": "Filosofia Política", **base},
    ] + [{"titulo": f"Professor de filosofia {i}", "area": "filosofia", "subarea": "", **base}
         for i in range(10)])  # "filosofia" comum, "lógica" rara

    ordem = list(_buscar(df, "filosofia da lógica").index)
    assert ordem[0] == 0, f"a vaga de lógica devia vir primeiro, veio a {ordem[0]}"

    ordem = list(_buscar(df, "filosofia política").index)
    assert ordem[0] == 2, f"a subárea 'Filosofia Política' devia vir primeiro, veio a {ordem[0]}"

    # quem casa os dois termos passa na frente de quem casa só um
    df2 = pd.concat([df, pd.DataFrame([{"titulo": "Professor de Filosofia da Lógica",
                                        "area": "filosofia", "subarea": "Lógica", **base}])],
                    ignore_index=True)
    assert list(_buscar(df2, "filosofia da lógica").index)[0] == len(df2) - 1
    print("OK  ordenação por especificidade")


if __name__ == "__main__":
    test_area()
    test_sinonimos()
    test_ordena_por_especificidade()
    test_area_no_corpo()
    test_busca_relevante()
    test_titulo_dou()
    test_anpof()
    print("todos passaram")

"""Privadas: reaproveita o varredor genérico com URLs de 'trabalhe conosco'.
ponytail: desligado por padrão no config; preencha paginas_privadas no config.yaml
com as instituições de interesse (ex.: PUC, Mackenzie, FGV) e ligue a fonte.
"""
from . import universidades_publicas
from ..database.models import Vaga


def buscar(paginas: list[dict], max_por_fonte: int = 100) -> list[Vaga]:
    vagas = universidades_publicas.buscar(paginas, max_por_fonte)
    for v in vagas:
        if v.classificacao_instituicao == "verificar manualmente":
            v.classificacao_instituicao = "privada"
        v.natureza = v.natureza if v.natureza != "não informado" else "emprego CLT"
    return vagas

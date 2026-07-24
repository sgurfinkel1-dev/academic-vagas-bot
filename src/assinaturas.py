"""Assinaturas de alerta por e-mail — cada pessoa que usa o dashboard pode pedir
para receber as vagas novas da sua área.

O arquivo assinaturas.yaml fica no repositório porque o disco do Streamlit Cloud é
efêmero: o dashboard grava via API do GitHub e o robô (GitHub Actions) lê no dia seguinte.
"""
import re
from pathlib import Path

import yaml

ARQUIVO = Path(__file__).resolve().parents[1] / "assinaturas.yaml"
EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def carregar(caminho: Path = ARQUIVO) -> list[dict]:
    if not caminho.exists():
        return []
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return dados.get("assinantes", [])


def serializar(assinantes: list[dict]) -> str:
    return yaml.safe_dump({"assinantes": assinantes}, allow_unicode=True, sort_keys=False)


def upsert(assinantes: list[dict], email: str, areas: list[str], ativo: bool = True) -> list[dict]:
    """Cria/atualiza a assinatura de um e-mail. Valida no limite de confiança:
    e-mail malformado é rejeitado (o dashboard é aberto a qualquer conta Google)."""
    email = (email or "").strip().lower()
    if not EMAIL_OK.match(email):
        raise ValueError(f"e-mail inválido: {email!r}")
    areas = [a.strip() for a in areas if a.strip()][:20]
    saida = [a for a in assinantes if a.get("email", "").lower() != email]
    if ativo:
        saida.append({"email": email, "areas": areas})
    return saida


def vagas_do_assinante(assinante: dict, vagas: list) -> list:
    """Filtra as vagas novas pelas áreas do assinante. Sem áreas = recebe todas."""
    areas = [a.lower() for a in assinante.get("areas", [])]
    if not areas:
        return vagas
    casadas = []
    for v in vagas:
        texto = f"{v.titulo} {v.area} {v.trecho_comprovacao}".lower()
        if any(a in texto for a in areas):
            casadas.append(v)
    return casadas


def _demo():
    """Checagem mínima da lógica de assinatura (upsert + filtro por área)."""
    from types import SimpleNamespace
    a = upsert([], "Fulano@Exemplo.COM ", ["Direito", " "])
    assert a == [{"email": "fulano@exemplo.com", "areas": ["Direito"]}], a
    a = upsert(a, "fulano@exemplo.com", ["Medicina"])          # atualiza, não duplica
    assert len(a) == 1 and a[0]["areas"] == ["Medicina"], a
    a = upsert(a, "fulano@exemplo.com", [], ativo=False)       # desativa remove
    assert a == [], a
    try:
        upsert([], "sem-arroba", [])
        raise AssertionError("deveria rejeitar e-mail inválido")
    except ValueError:
        pass
    v1 = SimpleNamespace(titulo="Professor de Direito Civil", area="", trecho_comprovacao="")
    v2 = SimpleNamespace(titulo="Bolsa em Química", area="", trecho_comprovacao="")
    assert vagas_do_assinante({"areas": ["direito"]}, [v1, v2]) == [v1]
    assert vagas_do_assinante({"areas": []}, [v1, v2]) == [v1, v2]   # sem área = tudo
    print("assinaturas: ok")


if __name__ == "__main__":
    _demo()

"""Integração com GitHub para o dashboard hospedado (Streamlit Cloud):
commitar a agenda.yaml e disparar a busca (workflow_dispatch).
Token e repositório vêm dos secrets do Streamlit; sem eles, tudo é no-op local.
"""
import base64
import httpx

API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def commitar_arquivo(repo: str, caminho: str, conteudo: str, token: str, msg: str) -> bool:
    """Cria/atualiza um arquivo no repo (para persistir a agenda editada no dashboard)."""
    url = f"{API}/repos/{repo}/contents/{caminho}"
    try:
        atual = httpx.get(url, headers=_headers(token), timeout=30)
        sha = atual.json().get("sha") if atual.status_code == 200 else None
        payload = {"message": msg, "content": base64.b64encode(conteudo.encode()).decode()}
        if sha:
            payload["sha"] = sha
        r = httpx.put(url, headers=_headers(token), json=payload, timeout=30)
        return r.status_code in (200, 201)
    except Exception:
        return False


def disparar_busca(repo: str, token: str, workflow: str = "daily.yml") -> bool:
    """workflow_dispatch: roda a busca completa na nuvem sob demanda."""
    url = f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    try:
        r = httpx.post(url, headers=_headers(token), json={"ref": "main"}, timeout=30)
        return r.status_code == 204
    except Exception:
        return False

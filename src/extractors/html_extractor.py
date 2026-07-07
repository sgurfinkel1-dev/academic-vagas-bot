import logging
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("bot")
# UA de navegador: in.gov.br, Cloudflare e afins recusam UAs de bot
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def baixar(url: str, timeout: float = 30) -> str:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning("falha ao baixar %s: %s", url, e)
        return ""


def baixar_json(url: str, params: dict | None = None, timeout: float = 30):
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("falha ao baixar json %s: %s", url, e)
        return None


def texto_da_pagina(html: str) -> str:
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True) if html else ""

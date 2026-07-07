import logging
import os
import httpx

log = logging.getLogger("bot")


def enviar(mensagem: str, cfg: dict) -> bool:
    url = os.getenv("DISCORD_WEBHOOK_URL") or cfg.get("webhook_url", "")
    if not url:
        log.warning("Discord não configurado (DISCORD_WEBHOOK_URL)")
        return False
    try:
        httpx.post(url, json={"content": mensagem[:1900]}).raise_for_status()
        return True
    except Exception as e:
        log.error("erro no alerta discord: %s", e)
        return False

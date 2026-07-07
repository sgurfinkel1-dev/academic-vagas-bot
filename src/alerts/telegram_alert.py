import logging
import os
import httpx

log = logging.getLogger("bot")


def enviar(mensagem: str, cfg: dict) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or cfg.get("chat_id", "")
    if not token or not chat_id:
        log.warning("Telegram não configurado (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat_id, "text": mensagem[:4000], "disable_web_page_preview": True})
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("erro no alerta telegram: %s", e)
        return False

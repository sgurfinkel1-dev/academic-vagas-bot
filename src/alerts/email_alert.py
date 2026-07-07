import logging
import os
import smtplib
from email.mime.text import MIMEText

log = logging.getLogger("bot")


def enviar(mensagem: str, cfg: dict) -> bool:
    usuario = os.getenv("SMTP_USER") or cfg.get("usuario", "")
    senha = os.getenv("SMTP_PASS", "")
    destinatario = cfg.get("destinatario") or usuario
    if not usuario or not senha:
        log.warning("E-mail não configurado (SMTP_USER/SMTP_PASS)")
        return False
    try:
        msg = MIMEText(mensagem, "plain", "utf-8")
        msg["Subject"] = "Novas vagas acadêmicas encontradas"
        msg["From"], msg["To"] = usuario, destinatario
        with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), int(cfg.get("smtp_port", 587))) as s:
            s.starttls()
            s.login(usuario, senha)
            s.send_message(msg)
        return True
    except Exception as e:
        log.error("erro no alerta e-mail: %s", e)
        return False

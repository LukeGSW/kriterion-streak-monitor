# ============================================================
# notifier.py — Invio email via Gmail SMTP (con allegato)
# ============================================================
# Stesso pattern dello Streak Monitor. Secrets:
#   GMAIL_ADDRESS, GMAIL_APP_PASSWORD
# In più: allega il report HTML come file, così resta archiviato
# nella mail oltre che renderizzato nel corpo.
# ============================================================

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_report(
    html_body: str,
    subject: Optional[str] = None,
    attachments: Optional[dict[str, str]] = None,
) -> bool:
    """
    Invia il report HTML via Gmail SMTP.

    Args:
        html_body:   HTML del corpo email
        subject:     oggetto (default con data)
        attachments: dict {filename: content_str} di allegati testuali
    """
    gmail_address  = os.environ.get('GMAIL_ADDRESS')
    gmail_app_pass = os.environ.get('GMAIL_APP_PASSWORD')

    if not gmail_address or not gmail_app_pass:
        logger.error("Credenziali Gmail mancanti (GMAIL_ADDRESS / GMAIL_APP_PASSWORD).")
        return False

    if subject is None:
        date_str = datetime.now(timezone.utc).strftime('%d/%m/%Y')
        subject = f"📊 Portfolio Allocator — Report {date_str}"

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = gmail_address
    msg['To'] = gmail_address

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText("Report disponibile in formato HTML.", 'plain', 'utf-8'))
    alt.attach(MIMEText(html_body, 'html', 'utf-8'))
    msg.attach(alt)

    for fname, content in (attachments or {}).items():
        part = MIMEApplication(content.encode('utf-8'), Name=fname)
        part['Content-Disposition'] = f'attachment; filename="{fname}"'
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_address, gmail_app_pass)
            server.sendmail(gmail_address, gmail_address, msg.as_string())
        logger.info(f"Email inviata a {gmail_address}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("Autenticazione Gmail fallita: verifica App Password e 2FA.")
        return False
    except Exception as e:
        logger.error(f"Errore invio email: {e}")
        return False

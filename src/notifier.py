# ============================================================
# notifier.py — Invio email via Gmail SMTP
# ============================================================
# Usa Gmail come sender e receiver (stesso account).
# Autenticazione tramite App Password Google (non la password
# normale dell'account — vedi README per la procedura).
#
# Credenziali lette da variabili d'ambiente (GitHub Secrets):
#   GMAIL_ADDRESS      → indirizzo Gmail mittente/destinatario
#   GMAIL_APP_PASSWORD → App Password a 16 caratteri Google
# ============================================================

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_report(html_body: str, subject: Optional[str] = None) -> bool:
    """
    Invia il report HTML via Gmail SMTP.

    Args:
        html_body: contenuto HTML dell'email (da report_builder)
        subject:   oggetto email (default con data odierna)

    Returns:
        True se inviata con successo, False altrimenti
    """
    gmail_address  = os.environ.get('GMAIL_ADDRESS')
    gmail_app_pass = os.environ.get('GMAIL_APP_PASSWORD')

    if not gmail_address or not gmail_app_pass:
        logger.error(
            "Credenziali Gmail mancanti. Imposta GMAIL_ADDRESS e "
            "GMAIL_APP_PASSWORD come GitHub Secrets."
        )
        return False

    if subject is None:
        date_str = datetime.utcnow().strftime('%d/%m/%Y')
        subject  = f"📊 Streak Monitor — Report {date_str}"

    # Costruisci il messaggio MIME multipart
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = gmail_address
    msg['To']      = gmail_address   # stesso account: sender = receiver

    # Attach il corpo HTML (fallback plain text minimo)
    plain_text = "Report disponibile solo in formato HTML. Aprire con un client email moderno."
    msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body,  'html',  'utf-8'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()   # connessione cifrata
            server.ehlo()
            server.login(gmail_address, gmail_app_pass)
            server.sendmail(gmail_address, gmail_address, msg.as_string())

        logger.info(f"Email inviata con successo a {gmail_address}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Autenticazione Gmail fallita. Verifica che:\n"
            "1. GMAIL_APP_PASSWORD sia un'App Password (non la password normale)\n"
            "2. La verifica in 2 passaggi sia attiva sull'account Google\n"
            "Guida: https://support.google.com/accounts/answer/185833"
        )
        return False

    except smtplib.SMTPException as e:
        logger.error(f"Errore SMTP: {e}")
        return False

    except Exception as e:
        logger.error(f"Errore inatteso durante l'invio email: {e}")
        return False


# Typing import mancante (compatibilità Python 3.9)
from typing import Optional

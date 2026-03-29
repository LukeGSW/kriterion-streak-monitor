# ============================================================
# drive_fetcher.py — Download CSV da Google Drive
# ============================================================
# Autentica con il service account Google, lista tutti i file
# nella cartella Drive configurata, scarica i CSV.
#
# Il service account JSON viene letto da variabile d'ambiente
# GOOGLE_SERVICE_ACCOUNT_JSON (impostata come GitHub Secret).
#
# Non richiede interazione manuale: il codice si autentica e
# scarica tutto automaticamente ad ogni run notturna.
# ============================================================

from __future__ import annotations

import io
import json
import logging
import os
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


# ─────────────────────────────────────────────
# Autenticazione
# ─────────────────────────────────────────────

def _get_drive_service():
    """
    Crea e ritorna il client Google Drive API autenticato.

    Legge le credenziali dal service account JSON nella variabile
    d'ambiente GOOGLE_SERVICE_ACCOUNT_JSON (stringa JSON raw).

    Returns:
        Resource Google Drive v3
    Raises:
        ValueError se la variabile d'ambiente non è impostata
        Exception se le credenziali sono invalide
    """
    sa_json_str = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not sa_json_str:
        raise ValueError(
            "Variabile d'ambiente GOOGLE_SERVICE_ACCOUNT_JSON non trovata.\n"
            "Impostala come GitHub Secret e aggiungila al workflow."
        )

    try:
        sa_info = json.loads(sa_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_SERVICE_ACCOUNT_JSON non è un JSON valido: {e}")

    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


# ─────────────────────────────────────────────
# Listing e download
# ─────────────────────────────────────────────

def list_csv_files(service, folder_id: str) -> list[dict]:
    """
    Lista tutti i file CSV nella cartella Drive specificata.

    Args:
        service:   client Drive autenticato
        folder_id: ID della cartella (dalla URL di Drive)

    Returns:
        Lista di dict con 'id', 'name', 'modifiedTime'
    """
    query = (
        f"'{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and name contains '.csv' "
        f"and trashed = false"
    )

    files   = []
    page_token = None

    while True:
        resp = service.files().list(
            q=query,
            spaces='drive',
            fields='nextPageToken, files(id, name, modifiedTime, size)',
            pageToken=page_token,
            pageSize=100,
        ).execute()

        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    logger.info(f"Drive: trovati {len(files)} file CSV nella cartella {folder_id}")
    return files


def download_file_content(service, file_id: str) -> str:
    """
    Scarica il contenuto di un file Drive come stringa UTF-8.

    Args:
        service: client Drive autenticato
        file_id: ID del file Drive

    Returns:
        Contenuto del file come stringa
    """
    request = service.files().get_media(fileId=file_id)
    buffer  = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    content = buffer.getvalue().decode('utf-8-sig', errors='replace')
    return content


# ─────────────────────────────────────────────
# Funzione principale
# ─────────────────────────────────────────────

def fetch_all_systems(folder_id: str) -> dict[str, dict[str, Optional[str]]]:
    """
    Scarica tutti i CSV dalla cartella Drive e li raggruppa per sistema.

    Ogni sistema ha due file possibili:
      - NomeSistema.csv        → trade chiusi (storico OOS)
      - NomeSistema_Open.csv   → trade aperto corrente (può essere vuoto)

    Returns:
        dict { system_name: { 'closed': str_content, 'open': str_content | None } }

    Esempio:
        {
          'BiasIntraweekAAPL': {
              'closed': '...csv content...',
              'open':   '...csv content...' or None
          },
          ...
        }
    """
    service = _get_drive_service()
    all_files = list_csv_files(service, folder_id)

    if not all_files:
        logger.warning("Nessun file CSV trovato nella cartella Drive.")
        return {}

    # Separa i file _Open da quelli storici
    open_files   = {f['name']: f for f in all_files if f['name'].endswith('_Open.csv')}
    closed_files = {f['name']: f for f in all_files if not f['name'].endswith('_Open.csv')}

    systems: dict[str, dict] = {}

    for csv_name, file_meta in closed_files.items():
        system_name = csv_name.replace('.csv', '')

        logger.info(f"Download: {csv_name} ({file_meta.get('size', '?')} bytes)")
        try:
            closed_content = download_file_content(service, file_meta['id'])
        except Exception as e:
            logger.error(f"Errore download {csv_name}: {e}")
            continue

        # Cerca il corrispondente _Open.csv
        open_csv_name = f"{system_name}_Open.csv"
        open_content  = None

        if open_csv_name in open_files:
            try:
                raw_open = download_file_content(service, open_files[open_csv_name]['id'])
                # Considera il file valido se contiene almeno una riga dati
                # con virgole (il formato _Open è una singola riga CSV ~93 byte)
                data_lines = [
                    l.strip() for l in raw_open.strip().splitlines()
                    if l.strip() and ',' in l
                ]
                if data_lines:
                    open_content = raw_open
                    logger.info(f"  → Trade aperto rilevato in {open_csv_name}")
                else:
                    logger.debug(f"  → {open_csv_name} vuoto, nessuna posizione aperta")
            except Exception as e:
                logger.warning(f"Errore download {open_csv_name}: {e}")

        systems[system_name] = {
            'closed': closed_content,
            'open':   open_content,
        }

    logger.info(f"Sistemi caricati da Drive: {len(systems)}")
    return systems

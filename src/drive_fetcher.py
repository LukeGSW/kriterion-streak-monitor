# ============================================================
# drive_fetcher.py — Download CSV da Google Drive
# ============================================================
# Identico al pattern dello Streak Monitor: autentica con il
# service account (GitHub Secret GOOGLE_SERVICE_ACCOUNT_JSON),
# lista TUTTI i CSV nella cartella e li scarica.
#
# Nessuna lista di sistemi hardcoded: qualsiasi sistema nuovo
# aggiunto alla cartella Drive viene incluso automaticamente.
# I file *_Open.csv vengono ignorati (non servono qui).
# ============================================================

from __future__ import annotations

import io
import json
import logging
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def _get_drive_service():
    sa_json_str = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not sa_json_str:
        raise ValueError(
            "Variabile d'ambiente GOOGLE_SERVICE_ACCOUNT_JSON non trovata.\n"
            "Impostala come GitHub Secret (stesso valore dello Streak Monitor)."
        )
    try:
        sa_info = json.loads(sa_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_SERVICE_ACCOUNT_JSON non è un JSON valido: {e}")

    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


def _list_csv_files(service, folder_id: str) -> list[dict]:
    query = (
        f"'{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and name contains '.csv' "
        f"and trashed = false"
    )
    files, page_token = [], None
    while True:
        resp = service.files().list(
            q=query, spaces='drive',
            fields='nextPageToken, files(id, name, modifiedTime, size)',
            pageToken=page_token, pageSize=100,
        ).execute()
        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    logger.info(f"Drive: trovati {len(files)} file CSV nella cartella {folder_id}")
    return files


def _download(service, file_id: str) -> str:
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode('utf-8-sig', errors='replace')


def fetch_all_closed_csvs(folder_id: str) -> dict[str, str]:
    """
    Scarica tutti i CSV di trade chiusi dalla cartella Drive.

    Returns:
        dict { system_name: csv_content } — i file _Open.csv sono esclusi.
    """
    service = _get_drive_service()
    all_files = _list_csv_files(service, folder_id)

    out: dict[str, str] = {}
    for f in all_files:
        name = f['name']
        if name.endswith('_Open.csv'):
            continue
        system_name = name[:-4]  # rimuove .csv
        try:
            out[system_name] = _download(service, f['id'])
            logger.info(f"Download: {name} ({f.get('size', '?')} bytes)")
        except Exception as e:
            logger.error(f"Errore download {name}: {e}")

    logger.info(f"Sistemi scaricati da Drive: {len(out)}")
    return out

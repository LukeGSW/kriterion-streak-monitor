# 📊 Streak Monitor — Kriterion Quant

Sistema automatico di analisi streak e gestione esposizione per portafogli
di trading system multipli. Ogni notte scarica i CSV da Google Drive,
calcola il moltiplicatore di sizing ottimale per ogni sistema con un
modello Bayesiano Beta-Binomiale, e invia un report email completo.

---

## Architettura

```
streak-monitor/
├── src/
│   ├── main.py            ← orchestratore pipeline notturna
│   ├── parser.py          ← parser universale CSV MultiCharts
│   ├── streak_engine.py   ← motore Bayesiano di analisi streak
│   ├── drive_fetcher.py   ← download da Google Drive API
│   ├── report_builder.py  ← generatore email HTML
│   └── notifier.py        ← invio email Gmail SMTP
├── dashboard/
│   └── app.py             ← Streamlit dashboard
├── state/
│   └── system_state.json  ← stato aggiornato ogni notte
├── config/
│   └── settings.yaml      ← configurazione (non le credenziali)
├── .github/workflows/
│   └── nightly.yml        ← GitHub Action 02:00 CET
└── requirements.txt
```

---

## Setup — Guida passo passo

### 1. Fork / crea il repository su GitHub

Crea un nuovo repository privato su GitHub e carica tutti i file.

### 2. Configura il Service Account Google Drive

**Recupera il service account esistente:**

1. Vai su [console.cloud.google.com](https://console.cloud.google.com)
2. Seleziona il tuo progetto Google Cloud
3. Menu → IAM e amministrazione → Account di servizio
4. Trova il service account esistente → clicca sui tre puntini → "Gestisci chiavi"
5. Se non hai chiavi attive: "Aggiungi chiave" → "Crea nuova chiave" → JSON → Scarica
6. Copia il **contenuto intero** del file JSON scaricato

**Condividi la cartella Drive con il service account:**

1. Apri la cartella Drive con i tuoi CSV
2. Clicca "Condividi"
3. Incolla l'email del service account (formato: `nome@progetto.iam.gserviceaccount.com`)
4. Permesso: **Visualizzatore** (sola lettura è sufficiente)
5. Clicca "Invia"

### 3. Configura l'App Password Gmail

1. Vai su [myaccount.google.com](https://myaccount.google.com)
2. Sicurezza → Verifica in due passaggi (deve essere attiva)
3. Sicurezza → App password
4. Seleziona "Posta" + "Mac" (o qualsiasi dispositivo)
5. Copia la **password a 16 caratteri** generata

### 4. Aggiungi i GitHub Secrets

Nel tuo repository GitHub:
**Settings → Secrets and variables → Actions → New repository secret**

Aggiungi questi tre secret:

| Nome | Valore |
|------|--------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Incolla l'intero contenuto del file JSON del service account |
| `GMAIL_ADDRESS` | Il tuo indirizzo Gmail (es. `tuoemail@gmail.com`) |
| `GMAIL_APP_PASSWORD` | L'App Password a 16 caratteri (senza spazi) |

### 5. Verifica settings.yaml

Controlla che `config/settings.yaml` abbia il `folder_id` corretto.
L'ID lo trovi nell'URL della cartella Drive:
`drive.google.com/drive/folders/`**`QUESTO_È_IL_FOLDER_ID`**

### 6. Test manuale

Per testare prima dell'orario notturno:
- GitHub → Actions → "Streak Monitor — Nightly Analysis" → "Run workflow"

Controlla i log per eventuali errori.

---

## Deploy Dashboard Streamlit

1. Vai su [share.streamlit.io](https://share.streamlit.io)
2. "New app" → seleziona il tuo repository → Main file path: `dashboard/app.py`
3. "Advanced settings" → Secrets → aggiungi:

```toml
GITHUB_STATE_URL = "https://raw.githubusercontent.com/TUO_UTENTE/streak-monitor/main/state/system_state.json"

# Solo se il repo è privato:
# GITHUB_TOKEN = "ghp_il_tuo_personal_access_token"
```

**Se il repo è privato**, genera un Personal Access Token:
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
Permesso: `Contents: Read-only` sul repository streak-monitor.

---

## Interpretazione del Report

### Moltiplicatori

| Badge | Significato | Azione |
|-------|-------------|--------|
| 🔵 **2×** | Segnale forte: alta prob. win dopo streak di loss, alta confidenza | Raddoppia l'esposizione sul prossimo trade |
| 🟢 **1.5×** | Segnale positivo: prob. win sopra soglia | Aumenta l'esposizione del 50% |
| ⬜ **1×** | Neutro: nessun segnale significativo | Mantieni esposizione base |
| 🟠 **0.5×** | Segnale difensivo: alta prob. loss | Riduci l'esposizione del 50% |

### Confidenza

La confidenza dipende dal numero di osservazioni storiche della streak corrente:
- 🟢 **Alta** (≥15 obs): segnale statisticamente robusto
- 🟡 **Media** (5-14 obs): segnale indicativo, massimo 1.5×
- 🔴 **Bassa** (<5 obs): campione insufficiente, sempre 1×

### Posizione aperta (● APERTA)

Il sistema ha un trade correntemente in corso. Il moltiplicatore indicato
si applica al **prossimo trade**, non a quello in corso.

---

## Personalizzazione soglie

Modifica `config/settings.yaml` per calibrare la sensibilità:

```yaml
sizing:
  thresholds:
    p_increase_15x: 0.65   # abbassa per segnali più frequenti
    p_increase_2x:  0.75   # abbassa per 2x più accessibile
    p_decrease_05x: 0.35   # alza per difesa più aggressiva
    n_min_low:      5      # abbassa per sistemi con pochi trade OOS
    n_min_medium:   15     # abbassa per sbloccare 2x prima
```

---

## Struttura CSV MultiCharts attesa

Il sistema riconosce automaticamente il formato di export standard MultiCharts:

```
TradeID,Strategia,Ticker,Tipo,DataEntrata,OraEntrata,DataUscita,OraUscita,
Direzione,PrezzoEntrata,PrezzoUscita,Quantità,Capitale,PnL$,PnL%,Bars
```

- **File storico** (`NomeSistema.csv`): tutti i trade chiusi OOS
- **File aperto** (`NomeSistema_Open.csv`): eventuale trade aperto corrente

Il codice si adatta automaticamente a qualsiasi ticker o strategia presente
nella cartella: non richiede configurazione per i nuovi sistemi.

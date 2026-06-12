# ⚖️ Portfolio Allocator — Kriterion Quant

Analisi trimestrale automatica dell'allocazione del portafoglio di trading
systems. Ogni trimestre scarica le equities da Google Drive, calcola i pesi
**inverse-volatility** per famiglia, li valida in walk-forward e invia un
report email con i pesi consigliati.

**Filosofia:** la volatilità delle famiglie è persistente nel tempo, lo
Sharpe no. Quindi si pesa per *rischio*, non si inseguono i rendimenti
passati. I pesi prodotti sono pesi di rischio — non giudizi di qualità dei
sistemi.

---

## Cosa fa ad ogni run

1. **Scarica tutti i CSV** dalla cartella Drive (stessa dello Streak Monitor).
   Nessuna lista hardcoded: **i sistemi aggiunti in futuro alla cartella
   entrano automaticamente nell'analisi**. I file `*_Open.csv` sono ignorati.
2. **Deduplica per trade_id** (i re-export giornalieri possono accodare righe
   duplicate) e applica l'eventuale normalizzazione size da `settings.yaml`.
3. **Sanity check con quarantena automatica**: sistemi con win rate > 90%,
   troppe righe duplicate o troppo pochi trade vengono esclusi e segnalati
   nel report con il motivo. File stale → warning.
4. **Analisi di allocazione**: vol e statistiche per famiglia, matrice di
   correlazione, contributo alla varianza di portafoglio, persistenza
   vol/Sharpe.
5. **Pesi inverse-volatility** (lookback 24 mesi, cap 0.5–2.0, gross
   invariato) arrotondati a step operativi di 0.25.
6. **Validazione walk-forward**: equal weight vs inverse-vol con
   ribilanciamento mensile out-of-sample + bootstrap sulla differenza di
   Sharpe.
7. **Report HTML via email** (tabelle e barre renderizzate direttamente in
   Gmail) + `output/weights_proposed.yaml` con i pesi pronti all'uso,
   committati nel repository.

---

## Setup

### 1. Crea il repository

Repository privato su GitHub, carica tutti i file.

### 2. GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret.**
Sono gli **stessi tre secret dello Streak Monitor** (copia i valori):

| Nome | Valore |
|------|--------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON completo del service account Drive |
| `GMAIL_ADDRESS` | Il tuo indirizzo Gmail |
| `GMAIL_APP_PASSWORD` | App Password a 16 caratteri |

### 3. Verifica settings.yaml

- `drive.folder_id`: già impostato sulla cartella delle equities.
- `families.prefixes`: prefissi che raggruppano i sistemi in famiglie.
  Un sistema che non matcha nessun prefisso diventa famiglia a sé.
- `size_normalization`: **importante** — da usare solo se un CSV è esportato
  a una size diversa da quella realmente tradata (es. equity full-size ma
  tradi il micro a 1/10 → fattore `0.1`). Se tutte le export sono alla size
  reale, lascia `{}`.

### 4. Prima esecuzione

GitHub → Actions → "Portfolio Allocator — Quarterly Analysis" →
**Run workflow**. Poi girerà da solo il 1° di gennaio, aprile, luglio e
ottobre alle 06:00 UTC.

---

## Interpretazione del report

| Sezione | Cosa guardare |
|---------|---------------|
| **Pesi consigliati** | Il numero operativo: moltiplicatore fisso per famiglia da applicare al size base fino al trimestre successivo |
| **Quarantena** | Sistemi esclusi per dati sospetti: verifica l'export su Drive prima del prossimo run |
| **Contributo al rischio** | Nessuna famiglia dovrebbe superare ~25% della varianza: se accade, il peso consigliato la sta già riducendo |
| **Persistenza vol/Sharpe** | Sanity del metodo: vol rank-corr alta (>0.7) e Sharpe bassa confermano l'approccio. Se la vol smettesse di essere persistente, fermarsi e rianalizzare |
| **Walk-forward** | Conferma out-of-sample che inverse-vol ha drawdown/vol migliori dell'equal weight sul TUO portafoglio |

**Regole d'uso:** applicare i pesi una volta a trimestre, non più spesso.
Non usare i pesi come classifica di qualità dei sistemi. Se una famiglia
finisce in quarantena, sistemare i dati prima di toccare i pesi.

---

## Riconciliazione con MultiCharts (da fare PRIMA di usare i pesi)

I pesi valgono solo se le equity su Drive sono identiche a quelle che vedi
su MultiCharts. Procedura una-tantum (e dopo ogni modifica agli export):

```bash
python src/verify.py            # legge da Drive (o --local /path/csv)
```

Per ogni sistema stampa **Net Profit**, **# Trades**, primo/ultimo trade e
la **% di entrate a minuto :00** (un sistema su dati minuto con 100% di
entrate a ore esatte è esportato dal chart sbagliato). Confronta i numeri
con lo Strategy Performance Report di MultiCharts:

1. Coincidono → `python src/verify.py --approve` e committa
   `output/fingerprints.json`: è la baseline di immutabilità.
2. Non coincidono → ri-esporta il sistema dal workspace corretto e ripeti.

Da quel momento **ogni run trimestrale verifica che lo storico non sia
mutato**: i trade passati non cambiano mai, quindi se il PnL di un anno
chiuso differisce dalla baseline il sistema va in quarantena automatica
(file rigenerato da timeframe/workspace/size diversi) e non entra nei pesi.
Per ri-approvare un sistema dopo una correzione voluta:
`python src/verify.py --approve NomeSistema`.

---

## Test locale (opzionale)

```bash
pip install -r requirements.txt
python src/main.py --local /percorso/cartella/csv --no-email
# output in output/report_YYYY-QX.html e output/weights_proposed.yaml
```

---

## Struttura

```
portfolio-allocator/
├── src/
│   ├── main.py            ← orchestratore
│   ├── parser.py          ← parser CSV MultiCharts (con dedup trade_id)
│   ├── drive_fetcher.py   ← download da Google Drive
│   ├── sanity.py          ← quarantena dati sospetti
│   ├── portfolio.py       ← motore allocazione + walk-forward
│   ├── report_builder.py  ← report HTML email-safe
│   └── notifier.py        ← invio Gmail SMTP con allegati
├── config/settings.yaml   ← configurazione (no credenziali)
├── output/                ← report e pesi (committati ad ogni run)
└── .github/workflows/quarterly.yml  ← cron trimestrale
```

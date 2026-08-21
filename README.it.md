# Google Search Console MCP

[English](README.md) · **Italiano**

[![CI](https://github.com/acamolese/google-search-console-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/acamolese/google-search-console-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-google-search-console)](https://pypi.org/project/mcp-google-search-console/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-google-search-console)](https://pypi.org/project/mcp-google-search-console/)
[![Licenza: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Diciassette tool in sola lettura sull'API di Google Search Console, più un report
di audit HTML deterministico e white-label che un'agenzia può firmare con il
proprio marchio e consegnare al cliente, in italiano o in inglese.

![Il report di audit generato](docs/report-preview.png)

Il report si rigenera da dati sintetici versionati nel repository, senza
credenziali:

```bash
python scripts/render_sample_report.py --lang it --open
```

## Installazione

### Claude Code

```bash
/plugin marketplace add acamolese/google-search-console-mcp
/plugin install google-search-console@acamolese
```

Il plugin porta con sé il server MCP, cinque skill (review settimanale, controllo
cannibalizzazione, audit di indicizzazione, opportunità di contenuto, audit
cliente white-label) e la richiesta guidata delle tre credenziali.

### Claude Desktop

Scaricare `google-search-console.mcpb` dall'
[ultima release](https://github.com/acamolese/google-search-console-mcp/releases)
e aprirlo. Richiede [uv](https://docs.astral.sh/uv/) installato. In alternativa,
modificando direttamente il file di configurazione:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"],
      "env": {
        "GSC_CLIENT_ID": "...",
        "GSC_CLIENT_SECRET": "...",
        "GSC_REFRESH_TOKEN": "..."
      }
    }
  }
}
```

### Cursor, Codex, Gemini CLI, Zed

Qualunque client MCP richiede le stesse tre righe: comando `uvx`, argomento
`mcp-google-search-console` e le tre variabili d'ambiente `GSC_*`.

```bash
# Codex
codex mcp add google-search-console -- uvx mcp-google-search-console

# Gemini CLI
gemini mcp add google-search-console uvx mcp-google-search-console
```

### Docker

```bash
docker build -t mcp-gsc .
docker run --rm -p 127.0.0.1:8765:8765 \
  -e GSC_CLIENT_ID -e GSC_CLIENT_SECRET -e GSC_REFRESH_TOKEN \
  -v "$PWD/reports:/reports" mcp-gsc
```

Il container espone il trasporto streamable HTTP su `/mcp`. Non ha
un'autenticazione propria: va tenuto su loopback oppure dietro un reverse proxy.

## Autenticazione

Lo scope OAuth richiesto è `webmasters.readonly` e nient'altro. Nessun tool di
questo server può modificare una proprietà, una sitemap o qualunque altra cosa
in Search Console.

Le credenziali vengono risolte in quest'ordine:

1. `GSC_AUTH_MODE` se impostata (`oauth`, `service_account`, `adc`)
2. `GSC_SERVICE_ACCOUNT_FILE` oppure `GSC_SERVICE_ACCOUNT_JSON`
3. `GSC_CLIENT_ID` + `GSC_CLIENT_SECRET` + `GSC_REFRESH_TOKEN`
4. Un file token in `~/.config/mcp-google-search-console/`
5. Application Default Credentials

### OAuth, una volta sola

1. Su [Google Cloud Console](https://console.cloud.google.com/) abilitare la
   **Google Search Console API** e creare un client OAuth di tipo
   **Applicazione desktop**.
2. Esportare le credenziali del client, oppure salvare il JSON scaricato come
   `~/.config/mcp-google-search-console/oauth_credentials.json`:

   ```bash
   export GSC_CLIENT_ID="...apps.googleusercontent.com"
   export GSC_CLIENT_SECRET="..."
   uvx mcp-google-search-console auth
   ```

3. Il flusso via browser stampa le tre righe `export` per una configurazione
   stateless e salva anche un token in
   `~/.config/mcp-google-search-console/token.json` con permessi `0600`.

Su una macchina headless conviene eseguire `auth` sul proprio computer e copiare
le tre variabili d'ambiente. L'opzione `--no-browser` stampa l'URL invece di
aprire il browser, ma richiede comunque un redirect locale.

### Service account

Va dato all'indirizzo email del service account l'accesso in lettura alla
proprietà in Search Console, poi si indica la chiave al server:

```bash
export GSC_SERVICE_ACCOUNT_FILE=/percorso/della/chiave.json
# oppure, dentro un container:
export GSC_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

### Verifica della configurazione

```bash
uvx mcp-google-search-console doctor
```

Stampa la modalità di autenticazione in uso, la scadenza del token, quante
proprietà l'account può leggere e i default applicati da tutti i tool. I segreti
sono mascherati. Esce con codice 1 quando non si risolve nessuna credenziale, che
è la risposta alla maggior parte delle segnalazioni "il server non parte".

## Tool

| Tool | A cosa risponde |
|---|---|
| `gsc_sites` | Quali proprietà può leggere questo account, e con quale stringa esatta |
| `gsc_site_details` | Livello di permesso e tipo di una proprietà |
| `gsc_query` | Il report Search Analytics, con filtri, dimensioni e paginazione |
| `gsc_performance_overview` | Il sito è in crescita o in calo rispetto al periodo precedente |
| `gsc_compare_periods` | Cosa è cambiato tra due periodi, ordinato per delta di click |
| `gsc_quick_wins` | Query abbastanza vicine alla vetta da giustificare una spinta |
| `gsc_ctr_gaps` | Pagine che si posizionano ma non ricevono click |
| `gsc_cannibalization` | Query su cui più pagine del sito competono tra loro |
| `gsc_traffic_drops` | Pagine che hanno perso click, ciascuna con una causa probabile |
| `gsc_content_decay` | Pagine che scendono mese dopo mese |
| `gsc_alerts` | Cosa si è mosso abbastanza da meritare una segnalazione oggi |
| `gsc_portfolio` | Tutte le proprietà a colpo d'occhio, dalla peggiore |
| `gsc_indexing_issues` | Quali di questi URL sono indicizzati, e perché gli altri no |
| `gsc_inspect_url` | URL Inspection completa su una singola pagina |
| `gsc_sitemaps` | Quali sitemap conosce Google, con errori e warning |
| `gsc_doctor` | Cosa è configurato e se l'API risponde |
| `gsc_audit` | Il report HTML completo |

Tre prompt coprono i flussi che si ripetono: `gsc_weekly_report`,
`gsc_indexing_audit`, `gsc_content_opportunities`.

## Perché questo server

| | Qui | Server GSC MCP tipico |
|---|---|---|
| Report per il cliente | HTML autonomo, italiano o inglese, white-label | assente |
| Analisi | Cannibalizzazione, gap di CTR, decay, diagnosi dei cali, lato server | righe grezze, analizzate dal modello |
| Soglie | Si adattano alla dimensione della proprietà | fisse, o assenti |
| Date | `period="last_month"`, `days=28`, risolte lato server | solo date esplicite |
| Freschezza | `dataState=all` di default, come l'interfaccia | solo `final` |
| Autenticazione | OAuth, service account, ADC | solo OAuth |
| Output | TSV di default, circa un terzo dei token del JSON indentato | `json.dumps(indent=2)` |
| Errori | Il motivo di Google più cosa farci | solo lo stato HTTP |
| Test | Oltre 280, su entrambe le major di `mcp` e tre sistemi operativi | di norma nessuno |

## Personalizzazione del report

Colori, logo, nome del report, termini di marca e soglie arrivano da un file
JSON. Si passa con `branding_path`, oppure si mette in
`~/.config/mcp-google-search-console/branding.json` per applicarlo ovunque:

```json
{
  "brand_name": "La tua agenzia",
  "logo": "logo.png",
  "brand_terms": ["marchiocliente", "marchio cliente"],
  "colors": { "primary": "#2b6cb0", "primary_dark": "#1a365d" },
  "thresholds": { "min_impressions": 200 }
}
```

Un logo locale viene codificato in base64 dentro il documento. Un logo remoto
viene mantenuto solo se `allow_external_fonts` è attivo, perché altrimenti il
report non contiene alcun URL esterno: niente CDN, niente servizi di font,
niente che contatti la rete quando il cliente apre il file.

`brand_terms` pesa più di quanto sembri. Senza, viene usata come marca la prima
label del dominio, che è sbagliata per sigle, holding e nomi di fantasia, e
classifica in silenzio come brand traffico che non lo è. Il report dichiara
quando ha dovuto tirare a indovinare.

## Quote e limiti

- **16 mesi** di dati giornalieri. Più indietro non è disponibile in alcun modo.
- **Dati orari**: solo gli ultimi 10 giorni.
- **URL Inspection**: 600 al minuto e **2.000 al giorno per proprietà**. È il
  limite che si sente davvero sui siti grandi.
- **Search Analytics**: 1.200 query al minuto per sito. Le risposte restano in
  cache in memoria per 6 ore (1 ora per le inspection); `no_cache=true` la
  aggira.
- **Righe**: 25.000 per chiamata API. I tool usano 100 di default con un tetto di
  1.000 e `start_row` per la paginazione; il tetto viene dichiarato nella
  risposta, mai applicato in silenzio.

## Variabili d'ambiente

| Variabile | Default | A cosa serve |
|---|---|---|
| `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` | | OAuth stateless |
| `GSC_SERVICE_ACCOUNT_FILE`, `GSC_SERVICE_ACCOUNT_JSON` | | Service account |
| `GSC_AUTH_MODE` | automatica | Forza `oauth`, `service_account` o `adc` |
| `GSC_REPORT_LANGUAGE` | `en` | Lingua del report: `en` o `it` |
| `GSC_DATA_STATE` | `all` | `all` include i dati parziali di oggi, `final` no |
| `GSC_CACHE_TTL_SECONDS` | `21600` | TTL della cache delle risposte; `0` la disattiva |
| `GSC_INSPECT_CONCURRENCY` | `5` | Inspection in parallelo |
| `GSC_LOG_LEVEL` | `WARNING` | Log, sempre su stderr |
| `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT` | `stdio` | Trasporto |

## Risoluzione dei problemi

**`spawn uvx ENOENT`** — il client non trova `uvx` nel PATH. Le applicazioni con
interfaccia grafica non ereditano il PATH della shell. Va indicato il percorso
assoluto: `which uvx` lo restituisce, tipicamente
`/Users/nome/.local/bin/uvx`.

**`403 forbidden` su ogni chiamata** — quasi sempre è il formato della proprietà.
Una proprietà di dominio è `sc-domain:example.com`, una con prefisso URL è
`https://example.com/`, barra finale inclusa. `gsc_sites` restituisce le stringhe
esatte.

**`401 invalid_grant`** — il refresh token è stato revocato o è scaduto. Google fa
scadere i refresh token delle app OAuth ancora in stato "testing" dopo sette
giorni: va pubblicata l'app, oppure rieseguito `auth`.

**`403 quotaExceeded`** — è finita la quota giornaliera di URL Inspection. Si
azzera il giorno dopo e nessun retry la aggira.

**Report vuoto su un sito piccolo** — vanno guardate le soglie nel blocco meta
della risposta. Si adattano alla proprietà, ma i minimi (50 impression, 10 click)
restano. Si abbassano passando `thresholds`.

**Qualunque altro caso** — eseguire `doctor` e allegarne l'output alla
segnalazione.

## Sicurezza

- Scope in sola lettura, richiesto e mai ampliato.
- I file token vengono scritti in modo atomico con permessi `0600`. Le credenziali
  fornite via ambiente non vengono mai scritte su disco.
- `gsc_doctor` maschera il client ID e non restituisce mai un token.
- Nessuna telemetria, nessun analytics, nessuna richiesta verso host diversi
  dall'API di Google.

La policy di segnalazione è in [SECURITY.md](SECURITY.md).

## Sviluppo

```bash
uv venv && uv pip install -e ".[dev]"
ruff check src tests scripts && ruff format --check src tests scripts
pytest -q --cov=google_search_console_mcp
python scripts/sync_versions.py
python scripts/render_sample_report.py --lang it --open
```

I test non toccano mai la rete. Esistono test live dietro `-m live`, che
richiedono `GSC_LIVE_TESTS=1` e credenziali; non girano mai in CI.

Per le release si veda [docs/RELEASING.md](docs/RELEASING.md). Le scelte non
coperte dal codice sono annotate in [docs/DECISIONS.md](docs/DECISIONS.md).

## Licenza

MIT. Chart.js 4.5.1 è incluso in `src/google_search_console_mcp/static/`, anch'esso
MIT, con la relativa licenza a fianco.

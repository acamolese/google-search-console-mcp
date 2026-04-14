<!-- mcp-name: io.github.acamolese/google-search-console-mcp -->

# Server MCP per Google Search Console

[![PyPI version](https://img.shields.io/pypi/v/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)
[![Python versions](https://img.shields.io/pypi/pyversions/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)
[![License: MIT](https://img.shields.io/pypi/l/mcp-google-search-console.svg)](https://github.com/acamolese/google-search-console-mcp/blob/main/LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)

Leggi questa pagina in: [English](README.md) | **Italiano**

**Server open source Model Context Protocol (MCP) per Google Search Console**. Porta i dati di performance, l'URL Inspection, i controlli di indicizzazione e le sitemap di Search Console dentro Claude Code, Claude Desktop, Cursor, Zed, Continue e qualunque client compatibile con MCP, e genera **report di audit SEO in HTML** completi e personalizzabili con una singola chiamata.

Se ti occupi di SEO e usi un assistente AI per programmare, questo server MCP elimina il copia-incolla tra Search Console e la chat: puoi chiedere le query che portano più clic, verificare se una lista di pagine è indicizzata, ispezionare un URL oppure generare una roadmap SEO a 30/60/90 giorni come report HTML, senza uscire dall'assistente.

## Caratteristiche

- **Accesso in sola lettura** a Search Console (nessuna operazione di scrittura sulle tue proprietà, viene richiesto solo lo scope OAuth `webmasters.readonly`)
- **8 tool** che coprono siti, query di performance, pagine, device, paesi, indicizzazione, sitemap e URL Inspection
- **`gsc_audit`**: generatore in un comando di un report HTML SEO autocontenuto, con grafici Chart.js, rilevamento automatico dei problemi, esempi concreti, strategia attuabile e roadmap a 30/60/90 giorni
- **Report brandizzabili**: personalizza logo, font e palette colori tramite `branding.json`, ideale per agenzie che consegnano audit white-label
- **Stateless-friendly**: credenziali via variabili d'ambiente (ottime per CI, Docker, MCP in hosting) oppure via directory di configurazione XDG
- **Zero setup con `uvx`**: nessun clone, nessun virtualenv, parte direttamente da PyPI
- **Compatibile con qualunque client MCP**: Claude Code, Claude Desktop, Cursor, Zed, Continue, Windsurf

## Perché usarlo

- Eviti l'interfaccia di Search Console quando stai già lavorando dentro al tuo assistente AI
- Trasformi i dati GSC in un audit HTML pronto da consegnare al cliente con un solo prompt
- Mantieni il pieno controllo sulle credenziali: variabili d'ambiente, directory XDG o layout legacy
- Sicuro per design: lo scope in sola lettura impedisce al server di modificare o rimuovere qualsiasi cosa dalle tue proprietà
- Python 3.10+, licenza MIT, pubblicato su PyPI come [`mcp-google-search-console`](https://pypi.org/project/mcp-google-search-console/)

## Tool disponibili

| Tool | Descrizione |
|---|---|
| `gsc_sites` | Elenca tutti i siti verificati |
| `gsc_site_details` | Dettagli di un sito specifico |
| `gsc_query` | Report di performance con dimensioni (query, page, country, device, date) |
| `gsc_performance_overview` | Metriche aggregate su un periodo (clic, impression, CTR, posizione) |
| `gsc_indexing_issues` | Verifica lo stato di indicizzazione di una lista di pagine |
| `gsc_inspect_url` | URL Inspection dettagliato di una singola pagina |
| `gsc_sitemaps` | Elenca tutte le sitemap inviate per un sito |
| `gsc_audit` | Genera un report HTML di audit completo per un intervallo di date |

## Installazione

### Opzione A: `uvx` (consigliata, zero setup)

Parte direttamente da PyPI, senza clone né virtualenv:

```bash
uvx mcp-google-search-console auth      # autorizzazione OAuth una tantum
uvx mcp-google-search-console            # avvia il server MCP
```

### Opzione B: `pipx`

```bash
pipx install mcp-google-search-console
mcp-google-search-console auth
mcp-google-search-console
```

### Opzione C: da sorgenti

```bash
git clone https://github.com/acamolese/google-search-console-mcp.git
cd google-search-console-mcp
uv venv && uv pip install -e .
.venv/bin/mcp-google-search-console auth
```

## Configurazione

### 1. Setup su Google Cloud

1. Vai su [Google Cloud Console](https://console.cloud.google.com/) e crea un progetto
2. Abilita la **Google Search Console API**
3. Apri **API e credenziali**, poi **Crea credenziali**, **ID client OAuth 2.0**, tipo **Applicazione desktop**
4. Scarica il JSON

### 2. Fornisci le credenziali OAuth

Hai tre modi, scegli quello più adatto al tuo setup. Il server li legge in quest'ordine:

**A. Variabili d'ambiente** (consigliate per headless, CI, Docker, MCP in hosting):

```bash
export GSC_CLIENT_ID="xxxxxxxxxxxx.apps.googleusercontent.com"
export GSC_CLIENT_SECRET="GOCSPX-xxxxxxxxxxxxxxxx"
export GSC_REFRESH_TOKEN="1//0xxxxxxxxxxxxxxxx"
```

Con queste tre variabili impostate il server è completamente stateless: non legge né scrive alcun file.

**B. Directory di configurazione XDG** (consigliata per uso desktop locale):

Salva il JSON delle credenziali OAuth come:

```
~/.config/mcp-google-search-console/oauth_credentials.json
```

Poi esegui il flusso di autorizzazione interattivo:

```bash
mcp-google-search-console auth
```

Si apre il browser, cattura il consenso OAuth e salva il refresh token in `~/.config/mcp-google-search-console/token.json`. Su Linux e macOS il percorso rispetta `$XDG_CONFIG_HOME` se impostato.

**C. Directory legacy per progetto** (solo retrocompatibilità):

Metti i file sotto `./credentials/oauth_credentials.json` e `./credentials/token.json` nella working directory da cui lanci il server. Questa modalità è ancora supportata per vecchi setup ma non è più raccomandata.

## Configurazione dei client MCP

Tutti gli esempi qui sotto assumono installazione con `uvx`. Adatta il comando se hai usato `pipx` (`mcp-google-search-console`) o clone da sorgenti (`/percorso/.venv/bin/mcp-google-search-console`).

### Claude Code

Modifica `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Claude Desktop

Modifica `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) o `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Cursor

Modifica `~/.cursor/mcp.json` (oppure il `.cursor/mcp.json` del progetto):

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Zed

Aggiungi al `settings.json` di Zed sotto `context_servers`:

```json
{
  "context_servers": {
    "google-search-console": {
      "command": {
        "path": "uvx",
        "args": ["mcp-google-search-console"]
      }
    }
  }
}
```

### Continue, Windsurf e altri client MCP

Qualunque client MCP che supporti i server stdio può usare lo stesso pattern:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Configurazione stateless con variabili d'ambiente

Se preferisci non persistere nulla su disco, passa le credenziali inline:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"],
      "env": {
        "GSC_CLIENT_ID": "xxxxxxxxxxxx.apps.googleusercontent.com",
        "GSC_CLIENT_SECRET": "GOCSPX-xxxxxxxxxxxxxxxx",
        "GSC_REFRESH_TOKEN": "1//0xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

## Esempi d'uso

Una volta che il server MCP è collegato al client, puoi chiedere cose come:

- "Elenca i miei siti verificati su Search Console"
- "Mostrami le prime 50 query per `sc-domain:example.com` degli ultimi 30 giorni"
- "Controlla se queste 5 pagine sono indicizzate: ..."
- "Genera un audit completo di `example.com` per il periodo 2026-01-01 → 2026-03-31"

Il tool `gsc_audit` scrive un file HTML autocontenuto in `~/gsc-reports/` e restituisce il percorso. Aprilo in qualunque browser.

### Suggerimenti

- Usa `sc-domain:example.com` per proprietà di dominio oppure `https://example.com/` per proprietà con prefisso URL.
- Dimensioni disponibili per `gsc_query`: `query`, `page`, `country`, `device`, `date` (combinabili con la virgola).
- Massimo 25.000 righe per richiesta.

## Personalizzare il report di audit

Il layout del report usa un template Jinja2 in `src/google_search_console_mcp/templates/report.html.j2` con colori e font guidati da `branding.json`.

Per personalizzarlo senza toccare il pacchetto, crea un tuo `branding.json` nella directory di configurazione XDG:

```
~/.config/mcp-google-search-console/branding.json
```

Esempio:

```json
{
  "brand_name": "Acme SEO Studio",
  "logo": "logo.png",
  "font_family": "Poppins",
  "font_url": "https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap",
  "colors": {
    "primary": "#ff6b35",
    "primary_dark": "#cc4a1f",
    "secondary": "#004e89",
    "accent": "#00b894",
    "danger": "#e74c3c",
    "warning": "#f39c12",
    "text": "#004e89",
    "text_muted": "#5a6c7d",
    "text_light": "#8395a7",
    "bg": "#f8f9fc",
    "surface": "#ffffff",
    "border": "#e1e8ed"
  }
}
```

Il campo `logo` accetta un nome di file locale (risolto rispetto alla directory XDG, poi a quella del pacchetto) oppure un URL completo. I file locali vengono codificati in base64 dentro l'HTML, così il report resta autocontenuto.

Puoi anche passare un file di branding diverso per ogni report tramite il parametro `branding_path` di `gsc_audit`:

> "Genera un audit di example.com usando il branding in `/percorso/client-branding.json`"

## FAQ

### Cos'è un server MCP?

MCP (Model Context Protocol) è un protocollo aperto che permette agli assistenti AI come Claude o Cursor di comunicare con sorgenti dati e tool esterni tramite un'interfaccia standard. Un server MCP espone un insieme di tool (funzioni) e risorse che l'assistente può invocare durante una conversazione. Questo progetto è un server MCP che espone Google Search Console come tool utilizzabili dal tuo assistente.

### Funziona con Claude Desktop, Claude Code, Cursor, Zed e Continue?

Sì. Qualunque client che parli MCP su stdio può usare questo server. Trovi snippet di configurazione pronti per ciascun client nella sezione [Configurazione dei client MCP](#configurazione-dei-client-mcp).

### Il server può modificare o cancellare dati dal mio account Search Console?

No. Viene richiesto a Google solo lo scope `webmasters.readonly`, che è in sola lettura per design. Il server non può inviare sitemap, richiedere indicizzazione o modificare alcuna impostazione della proprietà.

### Come ottengo le credenziali OAuth?

Crea un progetto Google Cloud, abilita la Google Search Console API, poi crea un **ID client OAuth 2.0** di tipo **Applicazione desktop** e scarica il JSON. Trovi i passaggi completi nella sezione [Configurazione](#configurazione).

### Posso usare un service account invece di OAuth?

Al momento no. L'API di Search Console richiede che l'identità abbia ricevuto accesso alla proprietà, e la documentazione di Google raccomanda credenziali utente OAuth per la maggior parte dei casi. Se ti serve il supporto service account, apri una issue.

### Posso personalizzare il report di audit SEO?

Sì. Metti un file `branding.json` in `~/.config/mcp-google-search-console/` per sovrascrivere logo, font e l'intera palette colori. Vedi [Personalizzare il report di audit](#personalizzare-il-report-di-audit). Puoi anche passare il parametro `branding_path` per singolo report quando chiami `gsc_audit`, opzione perfetta per le agenzie che producono audit white-label per più clienti.

### Dove vengono salvati i report di audit?

`gsc_audit` scrive un file HTML autocontenuto in `~/gsc-reports/` e restituisce il percorso. Il file è completamente inline (CSS, grafici, immagini in base64), quindi puoi condividerlo senza preoccuparti di asset esterni.

### Che differenza c'è tra `sc-domain:` e le proprietà con prefisso URL?

`sc-domain:example.com` copre l'intero dominio, inclusi tutti i sottodomini e sia `http` sia `https`. `https://example.com/` copre solo quel prefisso specifico. Usa la forma che corrisponde a come hai verificato la proprietà in Search Console.

### Funziona su server headless o in Docker?

Sì. Imposta `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` come variabili d'ambiente e salta del tutto il flusso browser `auth`. In questa modalità il server è completamente stateless e non scrive mai su disco.

## Sicurezza

- Non committare mai `oauth_credentials.json`, `token.json` o file `.env` con segreti reali.
- La directory di configurazione XDG è la posizione di default e sta fuori dalla repository.
- Il server richiede solo lo scope `webmasters.readonly`.

## Troubleshooting

- **401 Unauthorized alla prima chiamata**: token scaduto o mancante. Esegui `mcp-google-search-console auth` oppure imposta `GSC_REFRESH_TOKEN`.
- **"No OAuth client credentials found"**: né variabili d'ambiente né file sono configurati. Vedi la sezione Configurazione.
- **Il flusso browser fallisce su macchine headless**: salta del tutto `auth` ed esporta `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` come variabili d'ambiente.

## Migrazione da installazioni legacy (precedenti a `f2fe60e`)

Il pacchetto è stato ristrutturato nel commit `f2fe60e` e non include più un `server.py` a livello root. Se il tuo client MCP era configurato per avviare il server con `python server.py`, ora fallirà all'avvio con:

```
can't open file '.../server.py': [Errno 2] No such file or directory
```

Aggiorna la configurazione del client per usare l'entry-point installato:

```json
"google-search-console": {
  "command": "uvx",
  "args": ["mcp-google-search-console"]
}
```

Forme equivalenti sono elencate in [Configurazione dei client MCP](#configurazione-dei-client-mcp).

## Licenza

[MIT](LICENSE) © Andrea Camolese. Non affiliato a Google o Anthropic. "Google Search Console" è un marchio di Google LLC.

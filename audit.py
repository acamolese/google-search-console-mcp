"""Audit report generation for Google Search Console."""

import base64
import json
import mimetypes
import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT_BASE = "https://searchconsole.googleapis.com/v1"

PROJECT_DIR = Path(__file__).parent
TEMPLATES_DIR = PROJECT_DIR / "templates"
DEFAULT_BRANDING = PROJECT_DIR / "branding.json"


# ---------------------------------------------------------------------------
# Period and naming helpers
# ---------------------------------------------------------------------------

def previous_period(date_from: str, date_to: str) -> tuple[str, str]:
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    delta = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=delta - 1)
    return prev_from.isoformat(), prev_to.isoformat()


def site_slug(site_url: str) -> str:
    s = site_url.replace("sc-domain:", "")
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("/", "_").replace(".", "_").strip("_")
    return s


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------

DEFAULT_BRANDING_DICT = {
    "brand_name": "GSC Audit",
    "logo": "",
    "font_family": "Inter",
    "font_url": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
    "colors": {
        "primary": "#4299e1",
        "primary_dark": "#2b6cb0",
        "secondary": "#9f7aea",
        "accent": "#38a169",
        "danger": "#e53e3e",
        "warning": "#d69e2e",
        "text": "#1a365d",
        "text_muted": "#4a5568",
        "text_light": "#718096",
        "bg": "#f5f7fa",
        "surface": "#ffffff",
        "border": "#e2e8f0",
    },
}


def _embed_logo(logo_value: str) -> str:
    """Turn a local path or URL into an <img src=""> value.

    Local paths are base64-encoded so the report stays self-contained.
    URLs are returned as-is.
    """
    if not logo_value:
        return ""
    if logo_value.startswith(("http://", "https://", "data:")):
        return logo_value
    path = Path(logo_value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if not path.exists():
        return ""
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def load_branding(branding_path: str = "") -> dict:
    """Load branding config from JSON, falling back to defaults."""
    import copy
    branding = copy.deepcopy(DEFAULT_BRANDING_DICT)
    path = Path(branding_path).expanduser() if branding_path else DEFAULT_BRANDING
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            # Shallow merge with colors nested
            if "colors" in user:
                branding["colors"].update(user.pop("colors"))
            branding.update(user)
        except Exception:
            pass
    branding["logo_data"] = _embed_logo(branding.get("logo", ""))
    return branding


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _query(api_post, site_url: str, body: dict) -> list[dict]:
    encoded = urllib.parse.quote(site_url, safe="")
    data = api_post(f"{BASE}/sites/{encoded}/searchAnalytics/query", body)
    return data.get("rows", [])


def _overview(api_post, site_url: str, date_from: str, date_to: str) -> dict:
    rows = _query(api_post, site_url, {"startDate": date_from, "endDate": date_to})
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
    r = rows[0]
    return {
        "clicks": r.get("clicks", 0),
        "impressions": r.get("impressions", 0),
        "ctr": r.get("ctr", 0),
        "position": r.get("position", 0),
    }


def collect_data(api_get, api_post, site_url: str, date_from: str, date_to: str) -> dict:
    prev_from, prev_to = previous_period(date_from, date_to)

    current = _overview(api_post, site_url, date_from, date_to)
    previous = _overview(api_post, site_url, prev_from, prev_to)

    top_queries = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["query"], "rowLimit": 50,
    })
    top_pages = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["page"], "rowLimit": 50,
    })
    devices = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["device"],
    })
    countries = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["country"], "rowLimit": 15,
    })
    trend = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["date"], "rowLimit": 1000,
    })
    query_page = _query(api_post, site_url, {
        "startDate": date_from, "endDate": date_to,
        "dimensions": ["query", "page"], "rowLimit": 500,
    })

    encoded = urllib.parse.quote(site_url, safe="")
    try:
        sitemaps_data = api_get(f"{BASE}/sites/{encoded}/sitemaps")
        sitemaps = sitemaps_data.get("sitemap", [])
    except Exception:
        sitemaps = []

    indexing = []
    for row in top_pages[:10]:
        page_url = row["keys"][0]
        try:
            data = api_post(
                f"{INSPECT_BASE}/urlInspection/index:inspect",
                {"inspectionUrl": page_url, "siteUrl": site_url},
            )
            result = data.get("inspectionResult", {}).get("indexStatusResult", {})
            indexing.append({
                "url": page_url,
                "verdict": result.get("verdict", "UNKNOWN"),
                "coverageState": result.get("coverageState", ""),
            })
        except Exception as e:
            indexing.append({"url": page_url, "verdict": "ERROR", "coverageState": str(e)[:100]})

    # Flatten row records: copy `clicks`, `impressions`, `ctr`, `position` on top level
    # so templates can access q.clicks without .get()
    def _flatten(rows):
        for r in rows:
            r.setdefault("clicks", 0)
            r.setdefault("impressions", 0)
            r.setdefault("ctr", 0)
            r.setdefault("position", 0)
        return rows

    return {
        "site_url": site_url,
        "date_from": date_from,
        "date_to": date_to,
        "prev_from": prev_from,
        "prev_to": prev_to,
        "current": current,
        "previous": previous,
        "top_queries": _flatten(top_queries),
        "top_pages": _flatten(top_pages),
        "devices": _flatten(devices),
        "countries": _flatten(countries),
        "trend": _flatten(trend),
        "query_page": _flatten(query_page),
        "sitemaps": sitemaps,
        "indexing": indexing,
    }


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues(data: dict) -> list[dict]:
    issues = []

    # --- Paginated pages ------------------------------------------------------
    paginated = [p for p in data["top_pages"] if "?p=" in p["keys"][0] or "&p=" in p["keys"][0]]
    if paginated:
        total_clicks = sum(p.get("clicks", 0) for p in paginated)
        examples = [
            {"url": p["keys"][0], "clicks": int(p.get("clicks", 0)), "impressions": int(p.get("impressions", 0)), "position": f"{p.get('position', 0):.1f}"}
            for p in sorted(paginated, key=lambda x: x.get("clicks", 0), reverse=True)[:10]
        ]
        issues.append({
            "severity": "high",
            "category": "Indicizzazione",
            "title": f"{len(paginated)} pagine paginate indicizzate",
            "description": f"Le pagine paginate generano {int(total_clicks)} click complessivi e cannibalizzano le pagine principali della categoria. Google può scegliere canonicale diverso da quello dichiarato.",
            "examples": {"type": "pages", "rows": examples},
            "strategy": [
                "Aggiungere <link rel=\"canonical\"> su tutte le pagine paginate puntando alla prima pagina della categoria",
                "Verificare in GSC con URL Inspection che Google rispetti il canonical dichiarato",
                "In alternativa, valutare infinite scroll con history.pushState che mantiene l'URL principale",
                "Controllare che le paginate non siano linkate dalla sitemap XML",
                "Se le pagine 2+ hanno contenuti unici necessari per SEO, considerare una strategia rel=prev/next oppure URL SEO-friendly con titoli differenziati",
            ],
        })

    # --- HTTP version ---------------------------------------------------------
    http_pages = [p for p in data["top_pages"] if p["keys"][0].startswith("http://")]
    if http_pages:
        total_clicks = sum(p.get("clicks", 0) for p in http_pages)
        examples = [
            {"url": p["keys"][0], "clicks": int(p.get("clicks", 0)), "impressions": int(p.get("impressions", 0)), "position": f"{p.get('position', 0):.1f}"}
            for p in sorted(http_pages, key=lambda x: x.get("clicks", 0), reverse=True)[:10]
        ]
        issues.append({
            "severity": "high",
            "category": "Tecnico",
            "title": "Versione HTTP ancora indicizzata",
            "description": f"Rilevate {len(http_pages)} pagine HTTP con {int(total_clicks)} click nel periodo. La coesistenza di versione HTTP e HTTPS in indice diluisce i segnali SEO e può generare contenuti duplicati.",
            "examples": {"type": "pages", "rows": examples},
            "strategy": [
                "Configurare redirect 301 permanente da http:// a https:// a livello server (Apache/Nginx/CDN)",
                "Verificare che HSTS sia attivo con max-age di almeno un anno",
                "Aggiornare la sitemap XML con solo URL HTTPS e risottometterla",
                "Verificare con curl -I che ogni URL HTTP risponda 301 e non 302",
                "Richiedere la reindicizzazione delle versioni HTTPS tramite URL Inspection",
            ],
        })

    # --- Host mix -------------------------------------------------------------
    hostnames = set()
    for p in data["top_pages"]:
        url = p["keys"][0]
        if "://" in url:
            hostnames.add(url.split("://")[1].split("/")[0])
    base_hosts = set(h.replace("www.", "") for h in hostnames)
    if len(hostnames) > len(base_hosts):
        mixed_pages: dict = {}
        for p in data["top_pages"]:
            url = p["keys"][0]
            if "://" in url:
                host = url.split("://")[1].split("/")[0]
                mixed_pages[host] = mixed_pages.get(host, 0) + int(p.get("clicks", 0))
        examples_rows = [{"host": h, "clicks": c} for h, c in sorted(mixed_pages.items(), key=lambda x: -x[1])]
        issues.append({
            "severity": "medium",
            "category": "Tecnico",
            "title": "Host multipli indicizzati (www e non-www)",
            "description": f"Rilevati {len(hostnames)} hostname diversi che generano traffico: {', '.join(sorted(hostnames))}. Senza una versione canonica unica, i backlink e i segnali di autorità vengono distribuiti.",
            "examples": {"type": "hosts", "rows": examples_rows},
            "strategy": [
                "Scegliere una versione canonica (raccomandato: con www) e impostare redirect 301 da tutte le altre",
                "Aggiornare il canonical tag di ogni pagina verso l'hostname scelto",
                "Aggiornare tutti i link interni per usare l'hostname canonico",
                "Verificare la proprietà canonica in Google Search Console e richiedere la reindicizzazione",
            ],
        })

    # --- Low CTR on high-volume queries --------------------------------------
    low_ctr = [
        q for q in data["top_queries"]
        if q.get("impressions", 0) >= 2000 and q.get("ctr", 0) < 0.02 and q.get("position", 100) <= 10
    ]
    if low_ctr:
        examples = [
            {"query": q["keys"][0], "impressions": int(q.get("impressions", 0)), "ctr": f"{q.get('ctr', 0) * 100:.2f}%", "position": f"{q.get('position', 0):.1f}"}
            for q in sorted(low_ctr, key=lambda x: x.get("impressions", 0), reverse=True)[:10]
        ]
        issues.append({
            "severity": "medium",
            "category": "Contenuti",
            "title": f"{len(low_ctr)} query con CTR <2% in top 10",
            "description": "Query posizionate in prima pagina ma con click-through rate molto basso: il posizionamento c'è ma lo snippet non convince l'utente. Ottima opportunità a basso sforzo.",
            "examples": {"type": "queries", "rows": examples},
            "strategy": [
                "Riscrivere title tag inserendo USP differenzianti (prezzo, spedizione gratuita, made in Italy, non-iron)",
                "Aggiornare meta description con call-to-action chiare e limite 155 caratteri",
                "Implementare schema markup Product/Review/Offer per ottenere rich snippet (stelle, prezzo)",
                "Testare varianti di title con date/anno per creare percezione di freschezza",
                "Evitare title generici tipo \"Categoria | Brand\" e preferire formulazioni orientate al beneficio",
                "Monitorare CTR settimanale dopo ogni modifica e iterare",
            ],
        })

    # --- Page 2 opportunities ------------------------------------------------
    page_two = [q for q in data["top_queries"] if 10 < q.get("position", 0) <= 20 and q.get("impressions", 0) >= 500]
    if page_two:
        examples = [
            {"query": q["keys"][0], "impressions": int(q.get("impressions", 0)), "ctr": f"{q.get('ctr', 0) * 100:.2f}%", "position": f"{q.get('position', 0):.1f}"}
            for q in sorted(page_two, key=lambda x: x.get("impressions", 0), reverse=True)[:10]
        ]
        issues.append({
            "severity": "low",
            "category": "Opportunità",
            "title": f"{len(page_two)} query in posizione 11-20 con volume",
            "description": "Query in seconda pagina di Google che, con una spinta mirata, possono entrare in top 10 e aumentare significativamente il traffico.",
            "examples": {"type": "queries", "rows": examples},
            "strategy": [
                "Identificare la pagina che Google posiziona per ognuna di queste query",
                "Arricchire il contenuto della pagina con informazioni mancanti (FAQ, specifiche, comparazioni)",
                "Aggiungere link interni dalle pagine ad alta autorità verso queste pagine target",
                "Analizzare i top 10 risultati attuali per capire cosa li rende migliori e colmare il gap",
                "Verificare che le keyword siano presenti in H1, H2, URL e nei primi 100 parole",
                "Considerare backlink da publisher di settore se la competizione è alta",
            ],
        })

    # --- Weak high-visibility pages ------------------------------------------
    weak_pages = [p for p in data["top_pages"] if p.get("impressions", 0) >= 5000 and p.get("ctr", 0) < 0.015]
    if weak_pages:
        examples = [
            {"url": p["keys"][0], "clicks": int(p.get("clicks", 0)), "impressions": int(p.get("impressions", 0)), "position": f"{p.get('position', 0):.1f}"}
            for p in sorted(weak_pages, key=lambda x: x.get("impressions", 0), reverse=True)[:10]
        ]
        issues.append({
            "severity": "medium",
            "category": "Contenuti",
            "title": f"{len(weak_pages)} pagine ad alta visibilità con CTR <1.5%",
            "description": "Pagine con tante impression ma pochissimi click. Indicano una discrepanza tra snippet mostrato e intento dell'utente, oppure una posizione troppo bassa.",
            "examples": {"type": "pages", "rows": examples},
            "strategy": [
                "Fare una revisione di title e meta description pagina per pagina",
                "Verificare che il contenuto above-the-fold risponda all'intento di ricerca",
                "Controllare Core Web Vitals: un LCP alto può penalizzare i click mobile",
                "Valutare se la pagina è in cannibalizzazione con altre pagine del sito",
                "Implementare dati strutturati specifici per il tipo di pagina (Product, Article, FAQ)",
            ],
        })

    # --- Sitemap warnings ----------------------------------------------------
    warn_sitemaps = [s for s in data["sitemaps"] if int(s.get("warnings", 0)) > 0 or int(s.get("errors", 0)) > 0]
    if warn_sitemaps:
        total_warnings = sum(int(s.get("warnings", 0)) for s in warn_sitemaps)
        total_errors = sum(int(s.get("errors", 0)) for s in warn_sitemaps)
        examples_rows = [
            {"path": s.get("path", ""), "warnings": int(s.get("warnings", 0)), "errors": int(s.get("errors", 0)), "lastDownloaded": s.get("lastDownloaded", "")[:10]}
            for s in warn_sitemaps
        ]
        issues.append({
            "severity": "medium" if total_errors == 0 else "high",
            "category": "Tecnico",
            "title": f"Sitemap con {total_warnings} warning e {total_errors} errori",
            "description": "Le sitemap segnalate da Search Console presentano problemi: URL irraggiungibili, redirect dentro la sitemap, pagine noindex, URL non canonici.",
            "examples": {"type": "sitemaps", "rows": examples_rows},
            "strategy": [
                "Aprire Search Console → Sitemap → cliccare su ogni sitemap per leggere il dettaglio dei warning",
                "Rimuovere dalla sitemap gli URL che restituiscono redirect, 404 o noindex",
                "Verificare che tutti gli URL in sitemap siano HTTPS, canonici e senza parametri",
                "Assicurarsi che la sitemap non superi 50MB o 50.000 URL (altrimenti usare sitemap index)",
                "Risottomettere la sitemap pulita in Search Console",
                "Automatizzare la generazione della sitemap dal CMS se possibile",
            ],
        })

    # --- Indexing issues on top pages ----------------------------------------
    bad_index = [i for i in data["indexing"] if i["verdict"] not in ("PASS", "UNKNOWN")]
    if bad_index:
        examples_rows = [{"url": i["url"], "verdict": i["verdict"], "coverageState": i["coverageState"]} for i in bad_index]
        issues.append({
            "severity": "high",
            "category": "Indicizzazione",
            "title": f"{len(bad_index)} pagine top con problemi di indicizzazione",
            "description": "Pagine tra le più importanti del sito che Google non considera in stato PASS. Ogni pagina qui rappresenta traffico a rischio.",
            "examples": {"type": "indexing", "rows": examples_rows},
            "strategy": [
                "Per ogni pagina, aprire Search Console → URL Inspection per leggere il dettaglio",
                "Se coverage è \"Duplicate, Google chose different canonical\": verificare il canonical dichiarato e il contenuto unico",
                "Se è \"Crawled - currently not indexed\": migliorare qualità e unicità del contenuto",
                "Se è \"Discovered - currently not indexed\": problema di crawl budget, ridurre il numero di URL di bassa qualità",
                "Dopo ogni fix richiedere l'indicizzazione tramite il bottone \"Request indexing\"",
                "Monitorare lo stato settimanalmente nelle prime 2-3 settimane",
            ],
        })

    # --- Traffic trend -------------------------------------------------------
    cur_clicks = data["current"]["clicks"]
    prev_clicks = data["previous"]["clicks"]
    cur_imp = data["current"]["impressions"]
    prev_imp = data["previous"]["impressions"]
    if prev_clicks > 0:
        delta_pct = (cur_clicks - prev_clicks) / prev_clicks * 100
        if delta_pct < -10:
            imp_delta = ((cur_imp - prev_imp) / prev_imp * 100) if prev_imp > 0 else 0
            issues.append({
                "severity": "high",
                "category": "Performance",
                "title": f"Calo click {delta_pct:.1f}% vs periodo precedente",
                "description": f"Click passati da {int(prev_clicks):,} a {int(cur_clicks):,}. Impression variate del {imp_delta:+.1f}%. Necessaria indagine immediata sulle cause.",
                "examples": {"type": "metric", "rows": [
                    {"metric": "Click", "prev": f"{int(prev_clicks):,}", "curr": f"{int(cur_clicks):,}", "delta": f"{delta_pct:+.1f}%"},
                    {"metric": "Impression", "prev": f"{int(prev_imp):,}", "curr": f"{int(cur_imp):,}", "delta": f"{imp_delta:+.1f}%"},
                ]},
                "strategy": [
                    "Confrontare top 20 query e pagine nei due periodi per isolare dove è avvenuto il calo",
                    "Verificare eventuali Google Core Update nelle date del calo",
                    "Controllare modifiche recenti al sito: deploy, redirect, rimozione pagine, cambio template",
                    "Analizzare il log del server per individuare errori 5xx o blocchi del crawler",
                    "Verificare manual action e problemi di sicurezza in Search Console",
                    "Se il calo è su keyword specifiche, analizzare cosa stanno facendo i competitor che ti hanno superato",
                ],
            })

    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 9))
    return issues


# ---------------------------------------------------------------------------
# Strategy builder
# ---------------------------------------------------------------------------

STOPWORDS_IT = {
    "il", "la", "di", "e", "a", "in", "da", "per", "con", "su", "un", "una", "uno",
    "i", "gli", "le", "del", "della", "delle", "degli", "dei", "dello", "lo", "al",
    "alla", "alle", "agli", "ai", "allo", "nel", "nella", "nelle", "negli", "nei",
    "nello", "dal", "dalla", "dalle", "dagli", "dai", "dallo", "sul", "sulla",
    "sulle", "sugli", "sui", "sullo", "che", "chi", "cui", "come", "cosa", "dove",
    "quando", "quale", "quali", "quanto", "quanti", "se", "ma", "o", "ed", "ad",
    "non", "più", "meno", "molto", "poco", "anche",
}

CTR_BY_POSITION = {
    1: 0.275, 2: 0.155, 3: 0.100, 4: 0.075, 5: 0.060,
    6: 0.048, 7: 0.038, 8: 0.031, 9: 0.026, 10: 0.022,
}


def _expected_ctr(position: float) -> float:
    pos = max(1, min(10, int(round(position))))
    return CTR_BY_POSITION.get(pos, 0.015)


def _extract_brand(site_url: str) -> str:
    s = site_url.replace("sc-domain:", "").replace("https://", "").replace("http://", "")
    s = s.split("/")[0].replace("www.", "")
    return s.split(".")[0].lower()


def build_strategy(data: dict, issues: list[dict]) -> dict:
    brand = _extract_brand(data["site_url"])

    brand_clicks = brand_imp = 0
    non_brand_clicks = non_brand_imp = 0
    non_brand_queries = []
    for q in data["top_queries"]:
        text = q["keys"][0].lower()
        clicks = q.get("clicks", 0)
        imp = q.get("impressions", 0)
        if brand and brand in text.replace(" ", ""):
            brand_clicks += clicks
            brand_imp += imp
        else:
            non_brand_clicks += clicks
            non_brand_imp += imp
            non_brand_queries.append(q)

    total_clicks = brand_clicks + non_brand_clicks
    brand_pct = (brand_clicks / total_clicks * 100) if total_clicks > 0 else 0

    # Page 2 opportunities
    page_two_wins = []
    for q in data["top_queries"]:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        if 10 < pos <= 20 and imp >= 300:
            cur_clicks = q.get("clicks", 0)
            est_clicks = int(imp * _expected_ctr(5))
            uplift = max(0, est_clicks - cur_clicks)
            page_two_wins.append({
                "query": q["keys"][0],
                "impressions": int(imp),
                "ctr": f"{q.get('ctr', 0) * 100:.2f}%",
                "position": f"{pos:.1f}",
                "current_clicks": int(cur_clicks),
                "potential_clicks": est_clicks,
                "uplift": uplift,
            })
    page_two_wins.sort(key=lambda x: x["uplift"], reverse=True)
    page_two_wins = page_two_wins[:15]

    # High-potential pages
    high_potential = []
    for p in data["top_pages"]:
        imp = p.get("impressions", 0)
        ctr = p.get("ctr", 0)
        pos = p.get("position", 100)
        if imp >= 3000 and pos <= 15:
            expected = _expected_ctr(pos)
            if ctr < expected * 0.7:
                cur_clicks = p.get("clicks", 0)
                potential = int(imp * expected)
                uplift = max(0, potential - cur_clicks)
                high_potential.append({
                    "url": p["keys"][0],
                    "impressions": int(imp),
                    "ctr": f"{ctr * 100:.2f}%",
                    "expected_ctr": f"{expected * 100:.1f}%",
                    "position": f"{pos:.1f}",
                    "current_clicks": int(cur_clicks),
                    "potential_clicks": potential,
                    "uplift": uplift,
                })
    high_potential.sort(key=lambda x: x["uplift"], reverse=True)
    high_potential = high_potential[:10]

    # Top themes
    word_clicks: Counter = Counter()
    word_impressions: Counter = Counter()
    word_queries: dict = defaultdict(set)
    for q in non_brand_queries:
        text = q["keys"][0].lower()
        words = re.findall(r"[a-zàèéìòù]{4,}", text)
        for w in words:
            if w in STOPWORDS_IT or w == brand:
                continue
            word_clicks[w] += q.get("clicks", 0)
            word_impressions[w] += q.get("impressions", 0)
            word_queries[w].add(text)
    top_themes = [
        {
            "theme": word,
            "clicks": int(clicks),
            "impressions": int(word_impressions[word]),
            "query_count": len(word_queries[word]),
        }
        for word, clicks in word_clicks.most_common(15)
    ]

    # Cannibalization
    query_to_pages: dict = defaultdict(list)
    for row in data["query_page"]:
        query = row["keys"][0]
        page = row["keys"][1]
        query_to_pages[query].append({
            "page": page,
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "position": row.get("position", 0),
        })
    cannibalization = []
    for query, pages in query_to_pages.items():
        if len(pages) < 2:
            continue
        total = sum(p["clicks"] for p in pages)
        if total < 10:
            continue
        pages.sort(key=lambda x: x["clicks"], reverse=True)
        cannibalization.append({
            "query": query,
            "pages": pages[:4],
            "total_clicks": int(total),
            "page_count": len(pages),
        })
    cannibalization.sort(key=lambda x: x["total_clicks"], reverse=True)
    cannibalization = cannibalization[:10]

    # Featured snippet opportunities
    question_words = ("come", "cosa", "quando", "perché", "perche", "quale", "dove", "quanto", "chi")
    questions = []
    for q in data["top_queries"]:
        text = q["keys"][0].lower()
        first_word = text.split(" ")[0] if text else ""
        if first_word in question_words and q.get("position", 100) <= 15:
            questions.append({
                "query": q["keys"][0],
                "impressions": int(q.get("impressions", 0)),
                "ctr": f"{q.get('ctr', 0) * 100:.2f}%",
                "position": f"{q.get('position', 0):.1f}",
            })
    questions.sort(key=lambda x: x["impressions"], reverse=True)
    questions = questions[:10]

    # Geographic opportunities
    geo_opportunities = []
    if data["countries"]:
        primary_ctr = data["countries"][0].get("ctr", 0)
        for c in data["countries"][1:]:
            imp = c.get("impressions", 0)
            ctr = c.get("ctr", 0)
            if imp >= 500 and ctr > primary_ctr * 0.8:
                geo_opportunities.append({
                    "country": c["keys"][0].upper(),
                    "clicks": int(c.get("clicks", 0)),
                    "impressions": int(imp),
                    "ctr": f"{ctr * 100:.2f}%",
                    "position": f"{c.get('position', 0):.1f}",
                })

    # Device gap
    device_insights = None
    device_dict = {d["keys"][0]: d for d in data["devices"]}
    if "MOBILE" in device_dict and "DESKTOP" in device_dict:
        mob = device_dict["MOBILE"]
        desk = device_dict["DESKTOP"]
        gap = desk.get("position", 0) - mob.get("position", 0)
        total = mob.get("clicks", 0) + desk.get("clicks", 0)
        device_insights = {
            "mobile_position": f"{mob.get('position', 0):.1f}",
            "desktop_position": f"{desk.get('position', 0):.1f}",
            "gap": f"{gap:+.1f}",
            "mobile_share": (mob.get("clicks", 0) / total * 100) if total else 0,
            "has_gap": abs(gap) > 1.5,
        }

    total_uplift = sum(w["uplift"] for w in page_two_wins) + sum(p["uplift"] for p in high_potential)

    # Quick wins
    quick_wins = []
    if high_potential:
        top = high_potential[0]
        quick_wins.append({
            "title": "Riscrivere title e meta description sulle pagine ad alta visibilità",
            "impact": "Alto",
            "effort": "Basso",
            "action": f"Iniziare da {top['url']} ({top['impressions']:,} impression, CTR {top['ctr']} vs atteso {top['expected_ctr']}). Potenziale uplift: +{top['uplift']:,} click.",
        })
    if page_two_wins:
        top_pt = page_two_wins[0]
        quick_wins.append({
            "title": "Spingere le query in posizione 11-20 verso la top 10",
            "impact": "Alto",
            "effort": "Medio",
            "action": f"Focus sulla query '{top_pt['query']}' ({top_pt['impressions']:,} imp, pos {top_pt['position']}). Arricchire la pagina target con contenuti mancanti, link interni e schema markup.",
        })
    if cannibalization:
        top_cann = cannibalization[0]
        quick_wins.append({
            "title": "Risolvere la cannibalizzazione tra pagine",
            "impact": "Medio",
            "effort": "Medio",
            "action": f"La query '{top_cann['query']}' è divisa su {top_cann['page_count']} pagine. Consolidare canonical, rafforzare una sola pagina target per query.",
        })
    if any(i.get("severity") == "high" and "HTTP" in i.get("title", "") for i in issues):
        quick_wins.append({
            "title": "Forzare HTTPS ovunque con redirect 301",
            "impact": "Alto",
            "effort": "Basso",
            "action": "Configurare redirect 301 da HTTP a HTTPS a livello server, verificare HSTS, aggiornare sitemap e risottomettere.",
        })
    if any("paginate" in i.get("title", "") for i in issues):
        quick_wins.append({
            "title": "Canonicalizzare pagine paginate",
            "impact": "Medio",
            "effort": "Basso",
            "action": "Aggiungere rel=canonical dalle pagine ?p=N verso la pagina 1 della categoria per consolidare l'autorità.",
        })
    if questions:
        quick_wins.append({
            "title": "Ottimizzare per featured snippet e People Also Ask",
            "impact": "Medio",
            "effort": "Medio",
            "action": f"Rilevate {len(questions)} query interrogative in top 15. Aggiungere sezioni FAQ strutturate con risposte brevi (40-60 parole) e schema FAQPage.",
        })
    if brand_pct > 50:
        quick_wins.append({
            "title": "Ridurre la dipendenza dal traffico brand",
            "impact": "Alto",
            "effort": "Alto",
            "action": f"Il {brand_pct:.0f}% del traffico arriva da query brand. Investire in contenuti informativi top-of-funnel per allargare il bacino di utenti non-brand.",
        })
    if top_themes:
        top_theme = top_themes[0]
        quick_wins.append({
            "title": f"Creare contenuti hub sul tema '{top_theme['theme']}'",
            "impact": "Medio",
            "effort": "Alto",
            "action": f"Il tema '{top_theme['theme']}' concentra {top_theme['clicks']:,} click su {top_theme['query_count']} query. Creare una pagina pillar e cluster di contenuti di supporto.",
        })

    # Executive summary
    cur_clicks = data["current"]["clicks"]
    prev_clicks = data["previous"]["clicks"]
    trend_pct = ((cur_clicks - prev_clicks) / prev_clicks * 100) if prev_clicks > 0 else 0
    high_issues = len([i for i in issues if i.get("severity") == "high"])
    medium_issues = len([i for i in issues if i.get("severity") == "medium"])

    executive = {
        "trend_pct": trend_pct,
        "brand_pct": brand_pct,
        "non_brand_pct": 100 - brand_pct,
        "non_brand_clicks": int(non_brand_clicks),
        "high_issues": high_issues,
        "medium_issues": medium_issues,
        "total_uplift": int(total_uplift),
        "quick_win_count": len(quick_wins),
    }

    # Roadmap
    roadmap: dict = {"30": [], "60": [], "90": []}
    for i in issues:
        if i.get("severity") == "high":
            roadmap["30"].append(f"[CRITICO] {i['title']}")
    for qw in quick_wins[:3]:
        if qw.get("effort") == "Basso":
            roadmap["30"].append(qw["title"])
    if not roadmap["30"]:
        roadmap["30"].append("Nessun intervento critico urgente: procedere con ottimizzazioni di medio termine")

    for qw in quick_wins:
        if qw.get("effort") == "Medio":
            roadmap["60"].append(qw["title"])
    if page_two_wins:
        roadmap["60"].append(f"Ottimizzare {min(10, len(page_two_wins))} pagine target per le query in posizione 11-20")
    if cannibalization:
        roadmap["60"].append(f"Risolvere cannibalizzazione su {min(5, len(cannibalization))} query principali")

    if top_themes:
        roadmap["90"].append(f"Creare hub di contenuti sui temi principali: {', '.join(t['theme'] for t in top_themes[:3])}")
    if brand_pct > 40:
        roadmap["90"].append("Espandere il funnel con contenuti informativi per acquisire traffico non-brand")
    if geo_opportunities:
        countries_list = ", ".join(g["country"] for g in geo_opportunities[:3])
        roadmap["90"].append(f"Valutare localizzazione per mercati emergenti: {countries_list}")
    roadmap["90"].append("Analisi backlink e piano di digital PR per aumentare l'autorità del dominio")
    roadmap["90"].append("Audit dei competitor per identificare gap di contenuto")

    return {
        "executive": executive,
        "quick_wins": quick_wins,
        "page_two_wins": page_two_wins,
        "high_potential_pages": high_potential,
        "top_themes": top_themes,
        "cannibalization": cannibalization,
        "questions": questions,
        "geo_opportunities": geo_opportunities,
        "device_insights": device_insights,
        "roadmap": roadmap,
    }


# ---------------------------------------------------------------------------
# Rendering (Jinja2)
# ---------------------------------------------------------------------------

def _shorten_url(url: str, max_len: int = 60) -> str:
    s = url.replace("https://", "").replace("http://", "")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _delta_html(cur: float, prev: float, inverse: bool = False) -> str:
    if prev == 0:
        return '<span class="delta neutral">n/a</span>'
    pct = (cur - prev) / prev * 100
    positive = pct >= 0
    if inverse:
        positive = not positive
    cls = "positive" if positive else "negative"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span class="delta {cls}">{arrow} {pct:+.1f}%</span>'


def _build_kpis(data: dict) -> list[dict]:
    cur = data["current"]
    prev = data["previous"]
    return [
        {"label": "Click", "value": f"{int(cur['clicks']):,}", "delta": _delta_html(cur["clicks"], prev["clicks"])},
        {"label": "Impression", "value": f"{int(cur['impressions']):,}", "delta": _delta_html(cur["impressions"], prev["impressions"])},
        {"label": "CTR", "value": f"{cur['ctr'] * 100:.2f}%", "delta": _delta_html(cur["ctr"], prev["ctr"])},
        {"label": "Posizione media", "value": f"{cur['position']:.1f}", "delta": _delta_html(cur["position"], prev["position"], inverse=True)},
    ]


def _build_charts(data: dict) -> dict:
    return {
        "trend_labels": [r["keys"][0] for r in data["trend"]],
        "trend_clicks": [r.get("clicks", 0) for r in data["trend"]],
        "trend_impressions": [r.get("impressions", 0) for r in data["trend"]],
        "device_labels": [r["keys"][0] for r in data["devices"]],
        "device_clicks": [r.get("clicks", 0) for r in data["devices"]],
        "device_positions": [r.get("position", 0) for r in data["devices"]],
    }


def _render_example_table(examples: dict) -> str:
    """Render a small table inside an issue card. Pure HTML, no Jinja."""
    if not examples or not examples.get("rows"):
        return ""
    rows = examples["rows"]
    ex_type = examples.get("type", "")
    from html import escape as esc

    def row_td(items):
        return "".join(items)

    if ex_type == "pages":
        header = "<tr><th>URL</th><th>Click</th><th>Impression</th><th>Pos.</th></tr>"
        body = "".join(
            f"<tr><td class='url-cell'><a href='{esc(r.get('url', ''))}' target='_blank'>{esc(r.get('url', ''))}</a></td>"
            f"<td class='num'>{int(r.get('clicks', 0)):,}</td><td class='num'>{int(r.get('impressions', 0)):,}</td><td class='num'>{r.get('position', '')}</td></tr>"
            for r in rows
        )
    elif ex_type == "queries":
        header = "<tr><th>Query</th><th>Impression</th><th>CTR</th><th>Pos.</th></tr>"
        body = "".join(
            f"<tr><td>{esc(r.get('query', ''))}</td><td class='num'>{int(r.get('impressions', 0)):,}</td>"
            f"<td class='num'>{r.get('ctr', '')}</td><td class='num'>{r.get('position', '')}</td></tr>"
            for r in rows
        )
    elif ex_type == "hosts":
        header = "<tr><th>Host</th><th>Click</th></tr>"
        body = "".join(
            f"<tr><td><code>{esc(r['host'])}</code></td><td class='num'>{r['clicks']:,}</td></tr>"
            for r in rows
        )
    elif ex_type == "sitemaps":
        header = "<tr><th>Path</th><th>Warning</th><th>Errori</th><th>Ultimo download</th></tr>"
        body = "".join(
            f"<tr><td><code>{esc(r['path'])}</code></td><td class='num'>{r['warnings']}</td>"
            f"<td class='num'>{r['errors']}</td><td class='num'>{esc(r['lastDownloaded'])}</td></tr>"
            for r in rows
        )
    elif ex_type == "indexing":
        header = "<tr><th>URL</th><th>Verdetto</th><th>Stato</th></tr>"
        body = "".join(
            f"<tr><td class='url-cell'><a href='{esc(r['url'])}' target='_blank'>{esc(r['url'])}</a></td>"
            f"<td><strong>{esc(r['verdict'])}</strong></td><td>{esc(r['coverageState'])}</td></tr>"
            for r in rows
        )
    elif ex_type == "metric":
        header = "<tr><th>Metrica</th><th>Precedente</th><th>Attuale</th><th>Delta</th></tr>"
        body = "".join(
            f"<tr><td>{esc(r['metric'])}</td><td class='num'>{esc(r['prev'])}</td>"
            f"<td class='num'>{esc(r['curr'])}</td><td class='num'><strong>{esc(r['delta'])}</strong></td></tr>"
            for r in rows
        )
    else:
        return ""
    return f"<table class='examples-table'><thead>{header}</thead><tbody>{body}</tbody></table>"


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["shorten_url"] = _shorten_url
    return env


def render_html(data: dict, issues: list[dict], strategy: dict, branding: dict) -> str:
    env = _jinja_env()
    template = env.get_template("report.html.j2")
    return template.render(
        data=data,
        issues=issues,
        strategy=strategy,
        branding=branding,
        kpis=_build_kpis(data),
        charts=_build_charts(data),
        render_example=_render_example_table,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_audit(
    api_get,
    api_post,
    site_url: str,
    date_from: str,
    date_to: str,
    output_dir: str = "",
    branding_path: str = "",
) -> str:
    data = collect_data(api_get, api_post, site_url, date_from, date_to)
    issues = detect_issues(data)
    strategy = build_strategy(data, issues)
    branding = load_branding(branding_path)
    html_content = render_html(data, issues, strategy, branding)

    out_dir = Path(output_dir).expanduser() if output_dir else Path.home() / "gsc-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{site_slug(site_url)}_{date_from}_{date_to}.html"
    out_path = out_dir / filename
    out_path.write_text(html_content, encoding="utf-8")
    return str(out_path)

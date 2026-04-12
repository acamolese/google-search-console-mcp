"""Audit report generation for Google Search Console."""

import html
import json
import urllib.parse
from datetime import date, timedelta
from pathlib import Path


BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT_BASE = "https://searchconsole.googleapis.com/v1"


# ---------------------------------------------------------------------------
# Period helpers
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

    # Sitemaps
    encoded = urllib.parse.quote(site_url, safe="")
    try:
        sitemaps_data = api_get(f"{BASE}/sites/{encoded}/sitemaps")
        sitemaps = sitemaps_data.get("sitemap", [])
    except Exception:
        sitemaps = []

    # Indexing check on top 10 pages
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

    return {
        "site_url": site_url,
        "date_from": date_from,
        "date_to": date_to,
        "prev_from": prev_from,
        "prev_to": prev_to,
        "current": current,
        "previous": previous,
        "top_queries": top_queries,
        "top_pages": top_pages,
        "devices": devices,
        "countries": countries,
        "trend": trend,
        "sitemaps": sitemaps,
        "indexing": indexing,
    }


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues(data: dict) -> list[dict]:
    """Return a list of issue dicts with: severity, title, description, examples, strategy."""
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
            "description": f"Le pagine paginate (con parametro ?p=) generano {int(total_clicks)} click complessivi e cannibalizzano le pagine principali della categoria. Google può scegliere canonicale diverso da quello dichiarato.",
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

    # --- Host mix (www vs non-www, o altri subdomain) ------------------------
    hostnames = set()
    for p in data["top_pages"]:
        url = p["keys"][0]
        if "://" in url:
            host = url.split("://")[1].split("/")[0]
            hostnames.add(host)
    base_hosts = set(h.replace("www.", "") for h in hostnames)
    if len(hostnames) > len(base_hosts):
        mixed_pages = {}
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
    low_ctr = []
    for q in data["top_queries"]:
        imp = q.get("impressions", 0)
        ctr = q.get("ctr", 0)
        pos = q.get("position", 100)
        if imp >= 2000 and ctr < 0.02 and pos <= 10:
            low_ctr.append(q)
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

    # --- Page-2 opportunities (position 11-20 with decent volume) -------------
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
                "Identificare la pagina che Google posiziona per ognuna di queste query (usare la query query+page combinata)",
                "Arricchire il contenuto della pagina con informazioni mancanti (FAQ, specifiche, comparazioni)",
                "Aggiungere link interni dalle pagine ad alta autorità verso queste pagine target",
                "Analizzare i top 10 risultati attuali per capire cosa li rende migliori e colmare il gap",
                "Verificare che le keyword siano presenti in H1, H2, URL e nei primi 100 parole",
                "Considerare backlink da publisher di settore se la competizione è alta",
            ],
        })

    # --- High-impression pages with poor CTR ---------------------------------
    weak_pages = [p for p in data["top_pages"] if p.get("impressions", 0) >= 5000 and p.get("ctr", 0) < 0.015]
    if weak_pages:
        examples = [
            {"url": p["keys"][0], "impressions": int(p.get("impressions", 0)), "ctr": f"{p.get('ctr', 0) * 100:.2f}%", "position": f"{p.get('position', 0):.1f}"}
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
                    "Verificare eventuali Google Core Update nelle date del calo (Search Engine Roundtable, SERoundtable)",
                    "Controllare modifiche recenti al sito: deploy, redirect, rimozione pagine, cambio template",
                    "Analizzare il log del server per individuare errori 5xx o blocchi del crawler",
                    "Verificare manual action e problemi di sicurezza in Search Console",
                    "Se il calo è su keyword specifiche, analizzare cosa stanno facendo i competitor che ti hanno superato",
                ],
            })

    return issues


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_examples(examples: dict) -> str:
    if not examples or not examples.get("rows"):
        return ""
    rows = examples["rows"]
    ex_type = examples.get("type", "")

    if ex_type == "pages":
        header = "<tr><th>URL</th><th>Click</th><th>Impression</th><th>Pos.</th></tr>"
        body = "".join(
            f"<tr><td class=\"url-cell\"><a href=\"{html.escape(r['url'])}\" target=\"_blank\">{html.escape(r['url'])}</a></td>"
            f"<td class=\"num\">{r['clicks']:,}</td><td class=\"num\">{r['impressions']:,}</td><td class=\"num\">{r['position']}</td></tr>"
            for r in rows
        )
    elif ex_type == "queries":
        header = "<tr><th>Query</th><th>Impression</th><th>CTR</th><th>Pos.</th></tr>"
        body = "".join(
            f"<tr><td>{html.escape(r['query'])}</td><td class=\"num\">{r['impressions']:,}</td>"
            f"<td class=\"num\">{r['ctr']}</td><td class=\"num\">{r['position']}</td></tr>"
            for r in rows
        )
    elif ex_type == "hosts":
        header = "<tr><th>Host</th><th>Click</th></tr>"
        body = "".join(
            f"<tr><td><code>{html.escape(r['host'])}</code></td><td class=\"num\">{r['clicks']:,}</td></tr>"
            for r in rows
        )
    elif ex_type == "sitemaps":
        header = "<tr><th>Path</th><th>Warning</th><th>Errori</th><th>Ultimo download</th></tr>"
        body = "".join(
            f"<tr><td><code>{html.escape(r['path'])}</code></td><td class=\"num\">{r['warnings']}</td>"
            f"<td class=\"num\">{r['errors']}</td><td class=\"num\">{html.escape(r['lastDownloaded'])}</td></tr>"
            for r in rows
        )
    elif ex_type == "indexing":
        header = "<tr><th>URL</th><th>Verdetto</th><th>Stato</th></tr>"
        body = "".join(
            f"<tr><td class=\"url-cell\"><a href=\"{html.escape(r['url'])}\" target=\"_blank\">{html.escape(r['url'])}</a></td>"
            f"<td><strong>{html.escape(r['verdict'])}</strong></td><td>{html.escape(r['coverageState'])}</td></tr>"
            for r in rows
        )
    elif ex_type == "metric":
        header = "<tr><th>Metrica</th><th>Precedente</th><th>Attuale</th><th>Delta</th></tr>"
        body = "".join(
            f"<tr><td>{html.escape(r['metric'])}</td><td class=\"num\">{html.escape(r['prev'])}</td>"
            f"<td class=\"num\">{html.escape(r['curr'])}</td><td class=\"num\"><strong>{html.escape(r['delta'])}</strong></td></tr>"
            for r in rows
        )
    else:
        return ""

    return f'<div class="issue-examples"><div class="examples-label">Esempi ({len(rows)})</div><table class="examples-table"><thead>{header}</thead><tbody>{body}</tbody></table></div>'


def _delta_badge(cur: float, prev: float, inverse: bool = False) -> str:
    if prev == 0:
        return '<span class="delta neutral">n/a</span>'
    pct = (cur - prev) / prev * 100
    positive = pct >= 0
    if inverse:
        positive = not positive
    cls = "positive" if positive else "negative"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span class="delta {cls}">{arrow} {pct:+.1f}%</span>'


def _format_pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def render_html(data: dict, issues: list[dict]) -> str:
    site = data["site_url"]
    cur = data["current"]
    prev = data["previous"]

    # Trend data for Chart.js
    trend_labels = [r["keys"][0] for r in data["trend"]]
    trend_clicks = [r.get("clicks", 0) for r in data["trend"]]
    trend_impressions = [r.get("impressions", 0) for r in data["trend"]]

    # Device data for chart
    device_labels = [r["keys"][0] for r in data["devices"]]
    device_clicks = [r.get("clicks", 0) for r in data["devices"]]

    # Build query table
    query_rows = ""
    for q in data["top_queries"][:30]:
        query_rows += f"""
        <tr>
            <td>{html.escape(q['keys'][0])}</td>
            <td class="num">{int(q.get('clicks', 0)):,}</td>
            <td class="num">{int(q.get('impressions', 0)):,}</td>
            <td class="num">{_format_pct(q.get('ctr', 0))}</td>
            <td class="num">{q.get('position', 0):.1f}</td>
        </tr>"""

    page_rows = ""
    for p in data["top_pages"][:30]:
        url = p["keys"][0]
        short = url.replace("https://", "").replace("http://", "")
        if len(short) > 60:
            short = short[:57] + "..."
        page_rows += f"""
        <tr>
            <td><a href="{html.escape(url)}" target="_blank">{html.escape(short)}</a></td>
            <td class="num">{int(p.get('clicks', 0)):,}</td>
            <td class="num">{int(p.get('impressions', 0)):,}</td>
            <td class="num">{_format_pct(p.get('ctr', 0))}</td>
            <td class="num">{p.get('position', 0):.1f}</td>
        </tr>"""

    country_rows = ""
    for c in data["countries"]:
        country_rows += f"""
        <tr>
            <td>{html.escape(c['keys'][0].upper())}</td>
            <td class="num">{int(c.get('clicks', 0)):,}</td>
            <td class="num">{int(c.get('impressions', 0)):,}</td>
            <td class="num">{_format_pct(c.get('ctr', 0))}</td>
            <td class="num">{c.get('position', 0):.1f}</td>
        </tr>"""

    sitemap_rows = ""
    for s in data["sitemaps"]:
        warnings = int(s.get("warnings", 0))
        errors = int(s.get("errors", 0))
        status_cls = "ok" if warnings == 0 and errors == 0 else ("warn" if errors == 0 else "err")
        sitemap_rows += f"""
        <tr>
            <td><code>{html.escape(s.get('path', ''))}</code></td>
            <td class="num">{html.escape(s.get('lastDownloaded', '')[:10])}</td>
            <td class="num status-{status_cls}">{warnings}</td>
            <td class="num status-{status_cls}">{errors}</td>
        </tr>"""

    indexing_rows = ""
    for i in data["indexing"]:
        url = i["url"]
        short = url.replace("https://", "").replace("http://", "")
        if len(short) > 60:
            short = short[:57] + "..."
        verdict = i["verdict"]
        cls = "ok" if verdict == "PASS" else "warn"
        indexing_rows += f"""
        <tr>
            <td><a href="{html.escape(url)}" target="_blank">{html.escape(short)}</a></td>
            <td class="status-{cls}"><strong>{html.escape(verdict)}</strong></td>
            <td>{html.escape(i['coverageState'])}</td>
        </tr>"""

    issue_cards = ""
    if issues:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        for i in sorted(issues, key=lambda x: severity_order.get(x["severity"], 9)):
            examples_html = _render_examples(i.get("examples", {}))
            strategy_html = ""
            if i.get("strategy"):
                items = "".join(f"<li>{html.escape(s)}</li>" for s in i["strategy"])
                strategy_html = f'<div class="issue-strategy"><div class="strategy-label">Strategia consigliata</div><ol>{items}</ol></div>'
            category = i.get("category", "")
            category_html = f'<span class="issue-category">{html.escape(category)}</span>' if category else ""
            issue_cards += f"""
            <div class="issue issue-{i['severity']}">
                <div class="issue-header">
                    <span class="issue-severity">{i['severity'].upper()}</span>
                    {category_html}
                </div>
                <div class="issue-title">{html.escape(i['title'])}</div>
                <div class="issue-desc">{html.escape(i['description'])}</div>
                {examples_html}
                {strategy_html}
            </div>"""
    else:
        issue_cards = '<p class="empty">Nessuna criticità rilevata automaticamente.</p>'

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>Audit SEO - {html.escape(site)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fa; color: #1a202c; line-height: 1.5; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 40px 24px; }}
header {{ border-bottom: 3px solid #4299e1; padding-bottom: 24px; margin-bottom: 32px; }}
h1 {{ font-size: 28px; color: #1a365d; margin-bottom: 8px; }}
.subtitle {{ color: #4a5568; font-size: 15px; }}
h2 {{ font-size: 20px; color: #2d3748; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
.kpi-card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.kpi-label {{ font-size: 12px; text-transform: uppercase; color: #718096; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 28px; font-weight: 700; color: #1a365d; margin-top: 4px; }}
.delta {{ display: inline-block; font-size: 12px; font-weight: 600; margin-top: 6px; }}
.delta.positive {{ color: #38a169; }}
.delta.negative {{ color: #e53e3e; }}
.delta.neutral {{ color: #718096; }}
.chart-container {{ background: white; border-radius: 10px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 24px; height: 320px; }}
.chart-row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }}
.chart-row .chart-container {{ height: 280px; }}
table {{ width: 100%; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-collapse: collapse; }}
th {{ background: #edf2f7; text-align: left; padding: 12px 16px; font-size: 12px; text-transform: uppercase; color: #4a5568; font-weight: 600; letter-spacing: 0.5px; }}
td {{ padding: 12px 16px; border-top: 1px solid #e2e8f0; font-size: 14px; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td a {{ color: #3182ce; text-decoration: none; }}
td a:hover {{ text-decoration: underline; }}
code {{ background: #edf2f7; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
.status-ok {{ color: #38a169; }}
.status-warn {{ color: #d69e2e; }}
.status-err {{ color: #e53e3e; }}
.issue {{ background: white; border-left: 4px solid; border-radius: 6px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.issue-high {{ border-color: #e53e3e; }}
.issue-medium {{ border-color: #d69e2e; }}
.issue-low {{ border-color: #4299e1; }}
.issue-header {{ display: flex; gap: 10px; align-items: center; margin-bottom: 6px; }}
.issue-severity {{ display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; padding: 3px 8px; border-radius: 10px; background: #edf2f7; color: #4a5568; }}
.issue-high .issue-severity {{ background: #fed7d7; color: #c53030; }}
.issue-medium .issue-severity {{ background: #feebc8; color: #c05621; }}
.issue-low .issue-severity {{ background: #bee3f8; color: #2b6cb0; }}
.issue-category {{ font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
.issue-title {{ font-size: 17px; font-weight: 600; margin: 4px 0 8px; color: #1a365d; }}
.issue-desc {{ font-size: 14px; color: #4a5568; margin-bottom: 14px; }}
.issue-examples {{ margin: 14px 0; background: #f7fafc; border-radius: 6px; padding: 12px 14px; }}
.examples-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; font-weight: 600; margin-bottom: 8px; }}
.examples-table {{ width: 100%; background: transparent; box-shadow: none; border-radius: 0; }}
.examples-table th {{ background: transparent; padding: 6px 10px; font-size: 10px; color: #a0aec0; }}
.examples-table td {{ padding: 6px 10px; font-size: 12px; border-top: 1px solid #e2e8f0; }}
.examples-table td.url-cell {{ max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.issue-strategy {{ margin-top: 14px; background: #ebf8ff; border-left: 3px solid #4299e1; border-radius: 4px; padding: 12px 16px; }}
.strategy-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #2b6cb0; font-weight: 700; margin-bottom: 8px; }}
.issue-strategy ol {{ padding-left: 20px; font-size: 13px; color: #2c5282; }}
.issue-strategy li {{ margin-bottom: 4px; line-height: 1.5; }}
.empty {{ text-align: center; color: #718096; padding: 24px; background: white; border-radius: 10px; }}
footer {{ text-align: center; color: #a0aec0; font-size: 12px; margin-top: 48px; padding-top: 24px; border-top: 1px solid #e2e8f0; }}
</style>
</head>
<body>
<div class="container">
<header>
    <h1>Audit SEO - {html.escape(site)}</h1>
    <div class="subtitle">Periodo: {data['date_from']} → {data['date_to']} · Confronto con {data['prev_from']} → {data['prev_to']}</div>
</header>

<h2>Performance generale</h2>
<div class="kpi-grid">
    <div class="kpi-card">
        <div class="kpi-label">Click</div>
        <div class="kpi-value">{int(cur['clicks']):,}</div>
        {_delta_badge(cur['clicks'], prev['clicks'])}
    </div>
    <div class="kpi-card">
        <div class="kpi-label">Impression</div>
        <div class="kpi-value">{int(cur['impressions']):,}</div>
        {_delta_badge(cur['impressions'], prev['impressions'])}
    </div>
    <div class="kpi-card">
        <div class="kpi-label">CTR</div>
        <div class="kpi-value">{_format_pct(cur['ctr'])}</div>
        {_delta_badge(cur['ctr'], prev['ctr'])}
    </div>
    <div class="kpi-card">
        <div class="kpi-label">Posizione media</div>
        <div class="kpi-value">{cur['position']:.1f}</div>
        {_delta_badge(cur['position'], prev['position'], inverse=True)}
    </div>
</div>

<div class="chart-container">
    <canvas id="trendChart"></canvas>
</div>

<div class="chart-row">
    <div class="chart-container">
        <canvas id="deviceChart"></canvas>
    </div>
    <div class="chart-container">
        <canvas id="deviceClicksChart"></canvas>
    </div>
</div>

<h2>Criticità e opportunità</h2>
{issue_cards}

<h2>Top 30 query</h2>
<table>
    <thead><tr><th>Query</th><th style="text-align:right">Click</th><th style="text-align:right">Impression</th><th style="text-align:right">CTR</th><th style="text-align:right">Pos.</th></tr></thead>
    <tbody>{query_rows}</tbody>
</table>

<h2>Top 30 pagine</h2>
<table>
    <thead><tr><th>Pagina</th><th style="text-align:right">Click</th><th style="text-align:right">Impression</th><th style="text-align:right">CTR</th><th style="text-align:right">Pos.</th></tr></thead>
    <tbody>{page_rows}</tbody>
</table>

<h2>Top paesi</h2>
<table>
    <thead><tr><th>Paese</th><th style="text-align:right">Click</th><th style="text-align:right">Impression</th><th style="text-align:right">CTR</th><th style="text-align:right">Pos.</th></tr></thead>
    <tbody>{country_rows}</tbody>
</table>

<h2>Sitemap</h2>
<table>
    <thead><tr><th>Path</th><th style="text-align:right">Ultimo download</th><th style="text-align:right">Warning</th><th style="text-align:right">Errori</th></tr></thead>
    <tbody>{sitemap_rows}</tbody>
</table>

<h2>Indicizzazione top 10 pagine</h2>
<table>
    <thead><tr><th>Pagina</th><th>Verdetto</th><th>Stato copertura</th></tr></thead>
    <tbody>{indexing_rows}</tbody>
</table>

<footer>Report generato automaticamente · Google Search Console MCP</footer>
</div>

<script>
const trendCtx = document.getElementById('trendChart').getContext('2d');
new Chart(trendCtx, {{
    type: 'line',
    data: {{
        labels: {json.dumps(trend_labels)},
        datasets: [
            {{
                label: 'Click',
                data: {json.dumps(trend_clicks)},
                borderColor: '#4299e1',
                backgroundColor: 'rgba(66, 153, 225, 0.1)',
                yAxisID: 'y',
                tension: 0.3,
                fill: true,
            }},
            {{
                label: 'Impression',
                data: {json.dumps(trend_impressions)},
                borderColor: '#9f7aea',
                backgroundColor: 'rgba(159, 122, 234, 0.05)',
                yAxisID: 'y1',
                tension: 0.3,
                fill: false,
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ title: {{ display: true, text: 'Andamento giornaliero' }} }},
        scales: {{
            y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Click' }} }},
            y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'Impression' }}, grid: {{ drawOnChartArea: false }} }}
        }}
    }}
}});

const deviceCtx = document.getElementById('deviceChart').getContext('2d');
new Chart(deviceCtx, {{
    type: 'doughnut',
    data: {{
        labels: {json.dumps(device_labels)},
        datasets: [{{
            data: {json.dumps(device_clicks)},
            backgroundColor: ['#4299e1', '#9f7aea', '#ed8936'],
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ title: {{ display: true, text: 'Click per dispositivo' }} }}
    }}
}});

const deviceClicksCtx = document.getElementById('deviceClicksChart').getContext('2d');
new Chart(deviceClicksCtx, {{
    type: 'bar',
    data: {{
        labels: {json.dumps(device_labels)},
        datasets: [{{
            label: 'Posizione media',
            data: {json.dumps([r.get('position', 0) for r in data['devices']])},
            backgroundColor: '#4299e1',
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ title: {{ display: true, text: 'Posizione media per dispositivo' }}, legend: {{ display: false }} }},
        scales: {{ y: {{ reverse: true, beginAtZero: true }} }}
    }}
}});
</script>
</body>
</html>"""


def generate_audit(api_get, api_post, site_url: str, date_from: str, date_to: str, output_dir: str = "") -> str:
    data = collect_data(api_get, api_post, site_url, date_from, date_to)
    issues = detect_issues(data)
    html_content = render_html(data, issues)

    out_dir = Path(output_dir).expanduser() if output_dir else Path.home() / "gsc-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{site_slug(site_url)}_{date_from}_{date_to}.html"
    out_path = out_dir / filename
    out_path.write_text(html_content, encoding="utf-8")
    return str(out_path)

#!/usr/bin/env python3
"""
CMS SST Daily Problem Report
Generates an HTML report of CMS sites with issues, failing metrics and open GGUS tickets.

Data sources:
  - https://cmssst.web.cern.ch/sitereadiness/report.html  (SAM/HC/FTS per site, 16 days)
  - https://helpdesk.ggus.eu/api/v1/                       (GGUS tickets with description)

Usage:
  python3 cms_site_report.py [--token FILE] [--days N] [--out FILE] [--all]

  --token FILE   file containing the GGUS Bearer token (default: documentation/token_ggus)
  --days N       look back N days for metric issues (default: 3)
  --out FILE     HTML output file (default: cms_report.html)
  --all          include all sites, not only those with problems
"""

import argparse
import html
import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPORT_URL   = "https://cmssst.web.cern.ch/sitereadiness/report.html"
GGUS_API     = "https://helpdesk.ggus.eu/api/v1"
GGUS_TICKET_URL = "https://helpdesk.ggus.eu/#ticket/zoom/{id}"

COLOR_OK       = "#80FF80"
COLOR_WARNING  = "#FFFF00"
COLOR_ERROR    = "#FF0000"
COLOR_DOWNTIME = "#6080FF"
COLOR_PDTIME   = "#8080FF"
COLOR_ADHOC    = "#FF8000"

COLOR_LABELS = {
    COLOR_OK:       ("ok",       "ok"),
    COLOR_WARNING:  ("warning",  "warning"),
    COLOR_ERROR:    ("error",    "error"),
    COLOR_DOWNTIME: ("downtime", "downtime"),
    COLOR_PDTIME:   ("partial",  "partial"),
    COLOR_ADHOC:    ("adhoc",    "adhoc"),
}

STATUS_SEVERITY = {"error": 3, "partial": 2, "adhoc": 2, "warning": 1,
                   "downtime": 1, "ok": 0, "unknown": 0}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset)


def cell_status(bg_color):
    """Return status string from a cell's background colour."""
    c = (bg_color or "").upper().strip()
    for k, (short, _) in COLOR_LABELS.items():
        if c == k.upper():
            return short
    return "unknown"


def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text).strip()


def days_ago(ts_str):
    """Return how many days ago an ISO8601 timestamp was."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return delta.days
    except Exception:
        return 999


# ---------------------------------------------------------------------------
# Parse report.html
# ---------------------------------------------------------------------------
def parse_report(content, problem_days=3):
    """
    Ritorna dict: {site_name: {
        'dates':    [str, ...],        # ultime problem_days date (più recente = ultima)
        'SAM':      [{color, pct, tooltip, log_url}, ...],
        'HC':       [{color, pct, tooltip, log_url}, ...],
        'FTS':      [{color, pct, tooltip, log_url}, ...],
        'ggus_old': [ticket_id, ...],  # ticket GGUS dal vecchio sistema (ggus.eu)
        'max_severity': int,
    }}
    """

    # Normalizza spazi
    content = re.sub(r"\s+", " ", content)

    # --- Estrai le informazioni sito per sito ---
    # Ogni sito inizia con: <A NAME="T?_...">sitename</A>
    site_blocks = re.split(r'<A NAME="(T\d_[A-Z]{2}_\w+)">', content)
    # site_blocks[0] = testo prima del primo sito
    # poi a coppie: site_name, block_content

    sites = {}
    i = 1
    while i < len(site_blocks) - 1:
        site_name = site_blocks[i]
        block = site_blocks[i + 1]
        i += 2

        # Ferma il block al prossimo sito
        next_site = block.find('<A NAME="T')
        if next_site > 0:
            block = block[:next_site]

        site_data = {
            "dates":    [],
            "SAM":      [],
            "HC":       [],
            "FTS":      [],
            "ggus_old": [],
            "max_severity": 0,
        }

        # --- Ticket GGUS dal vecchio sistema (link ggus.eu) ---
        for tid in re.findall(
            r'ggus\.eu/\?mode=ticket_info&ticket_id=(\d+)', block
        ):
            site_data["ggus_old"].append(tid)

        # --- Righe metriche ---
        # Pattern cella con tooltip:
        # STYLE="background-color: #RRGGBB"><A ... HREF="...">PCT%<SPAN>tooltip</SPAN></A>
        row_pattern = re.compile(
            r'CLASS="tdLabel1">(.*?)[<\n].*?'   # label
            r'((?:<TD[^>]*>.*?)+?)(?=<TR|$)',    # celle della riga
            re.DOTALL
        )

        cell_pattern = re.compile(
            r'background-color:\s*(#[0-9A-Fa-f]{6})[^>]*>'
            r'<A[^>]+HREF="([^"]*)"[^>]*>([^<]*)<SPAN>(.*?)</SPAN>',
            re.DOTALL
        )

        # Usa approccio più semplice: trova le righe per label
        for metric_label, js_key in [
            ("SAM Status:", "SAM"),
            ("Hammer Cloud:", "HC"),
            ("FTS Status:", "FTS"),
        ]:
            idx = block.find(metric_label)
            if idx < 0:
                continue
            # Prende la riga fino al prossimo <TR
            row_end = block.find("<TR", idx + 10)
            row_html = block[idx:row_end] if row_end > 0 else block[idx:idx+4000]

            cells = cell_pattern.findall(row_html)
            # Tiene solo le ultime problem_days celle (più recenti)
            cells = cells[-problem_days:]
            for color, log_url, pct, tooltip in cells:
                status = cell_status(color)
                site_data[js_key].append({
                    "color":   color,
                    "status":  status,
                    "pct":     pct.strip(),
                    "tooltip": html.unescape(strip_tags(tooltip)),
                    "log_url": log_url,
                })
                sev = STATUS_SEVERITY.get(status, 0)
                if sev > site_data["max_severity"]:
                    site_data["max_severity"] = sev

        sites[site_name] = site_data

    return sites


# ---------------------------------------------------------------------------
# Fetch GGUS tickets
# ---------------------------------------------------------------------------
def fetch_ggus_tickets(token, max_batches=64):
    """
    Return dict: {cms_site_name: [{id, number, title, state, priority,
                                    created_at, updated_at, body}, ...]}
    """
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type":  "application/json; charset=UTF-8",
        "User-Agent":    "cms-site-report",
    }

    QUERY = ("(!((state.name:solved)OR(state.name:unsolved)OR"
             "(state.name:closed)OR(state.name:verified))AND id:>%d)")
    PARAMS = "&sort_by=id&order_by=asc&limit=32&expand=false"

    ticket_list = []
    last_id = 0
    for _ in range(max_batches):
        q = urllib.parse.quote_plus(QUERY % last_id)
        url = f"{GGUS_API}/tickets/search?query={q}{PARAMS}"
        try:
            data = json.loads(fetch(url, headers))
        except Exception as e:
            print(f"[WARN] GGUS fetch error: {e}", file=sys.stderr)
            break
        if not data:
            break
        ticket_list.extend(data)
        last_id = int(data[-1]["id"])

    # Raggruppa per sito CMS
    site_pattern = re.compile(r"T\d_[A-Z]{2}_\w+")
    by_site = {}

    for t in ticket_list:
        # Determina sito CMS
        cms_site = None
        if t.get("cms_site_names"):
            m = site_pattern.search(str(t["cms_site_names"]))
            if m:
                cms_site = m.group(0)
        if not cms_site:
            continue  # skip tickets without an identifiable CMS site

        # Fetch primo articolo (descrizione)
        body = ""
        art_ids = t.get("article_ids", [])
        if art_ids:
            try:
                art_url = f"{GGUS_API}/ticket_articles/{art_ids[0]}"
                art = json.loads(fetch(art_url, headers))
                raw = art.get("body", "")
                body = html.unescape(strip_tags(raw))[:800]
            except Exception:
                pass

        # Classifica: CMS VO se vo_support=='cms' o area inizia con 'CMS'
        vo = (t.get("vo_support") or "").lower()
        area = (t.get("area") or "")
        is_cms = (vo == "cms") or area.upper().startswith("CMS")

        entry = {
            "id":         t["id"],
            "number":     t.get("number", ""),
            "title":      t.get("title", ""),
            "state":      t.get("state", ""),
            "priority":   t.get("priority", ""),
            "created_at": t.get("created_at", ""),
            "updated_at": t.get("updated_at", ""),
            "body":       body,
            "is_cms":     is_cms,
        }
        by_site.setdefault(cms_site, []).append(entry)

    return by_site


# ---------------------------------------------------------------------------
# Generate HTML report
# ---------------------------------------------------------------------------
def severity_label(sev):
    if sev >= 3: return ("ERROR", "#FF4444")
    if sev >= 2: return ("PARTIAL/ADHOC", "#FF8800")
    if sev >= 1: return ("WARNING", "#CCCC00")
    return ("OK", "#44BB44")


def metric_html(cells, metric_name):
    if not cells:
        return f"<td class='metric-name'>{metric_name}</td><td class='no-data' colspan='3'>— no data —</td>"

    out = f"<td class='metric-name'>{metric_name}</td>"
    for cell in cells:
        bg = cell["color"] or "#F4F4F4"
        pct = cell["pct"] or "?"
        tooltip = cell["tooltip"].replace('"', "&quot;")
        log = cell.get("log_url", "#")
        out += (
            f'<td class="metric-cell" style="background:{bg}" title="{tooltip}">'
            f'<a href="{log}" target="_blank">{pct}</a></td>'
        )
    # padding se meno di 3 celle
    for _ in range(3 - len(cells)):
        out += "<td class='metric-cell empty'>&mdash;</td>"
    return out


def ticket_age_class(created_at):
    d = days_ago(created_at)
    if d > 30: return "ticket-old"
    if d > 7:  return "ticket-week"
    return "ticket-new"


def generate_html(sites_data, ggus_by_site, problem_days, show_all):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def tier_num(site):
        m = re.match(r"T(\d)", site)
        return int(m.group(1)) if m else 9

    # Filter: only ERROR sites (severity >= 3), sort by tier then alphabetically
    site_list = sorted(
        sites_data.items(),
        key=lambda kv: (tier_num(kv[0]), kv[0])
    )
    if not show_all:
        site_list = [
            (s, d) for s, d in site_list
            if d["max_severity"] >= 3 and not s.startswith("T2_RU_")
        ]

    n_problems = sum(
        1 for s, d in site_list
        if d["max_severity"] > 0 or s in ggus_by_site
    )

    # --- CSS + HTML ---
    html_out = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMS SST Daily Report — {now_str}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: monospace; font-size: 13px; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 16px; }}
  h1   {{ color: #a8d8ea; font-size: 18px; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 12px; margin-bottom: 24px; }}
  .summary {{ background: #16213e; border: 1px solid #0f3460; border-radius: 6px;
              padding: 10px 16px; margin-bottom: 20px; display: flex; gap: 24px; }}
  .summary span {{ font-size: 13px; }}
  .badge-err  {{ background: #FF4444; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: bold; }}
  .badge-ok   {{ background: #44BB44; color: #fff; padding: 2px 8px; border-radius: 4px; }}

  .site-block {{ border: 1px solid #0f3460; border-radius: 6px; margin-bottom: 16px;
                 overflow: hidden; }}
  .site-header {{ display: flex; align-items: center; gap: 12px;
                  padding: 8px 14px; background: #0f3460; }}
  .site-name   {{ font-size: 15px; font-weight: bold; color: #a8d8ea; }}
  .site-name a {{ color: inherit; text-decoration: none; }}
  .site-name a:hover {{ text-decoration: underline; }}
  .sev-badge   {{ padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
  .site-tier   {{ color: #888; font-size: 11px; }}
  .ticket-count {{ margin-left: auto; font-size: 11px; color: #ffd700; }}

  .site-body   {{ padding: 12px 14px; }}

  /* Tabella metriche */
  .metrics-table {{ border-collapse: collapse; margin-bottom: 14px; }}
  .metrics-table th {{ color: #888; font-weight: normal; font-size: 11px;
                       text-align: right; padding: 2px 6px; }}
  .metric-name {{ color: #aaa; padding: 3px 8px 3px 0; white-space: nowrap; min-width: 110px; }}
  .metric-cell {{ width: 80px; text-align: center; padding: 4px 6px;
                  border: 1px solid #333; border-radius: 3px; }}
  .metric-cell a {{ color: #1a1a2e; text-decoration: none; font-weight: bold; font-size: 12px; }}
  .metric-cell.empty {{ background: #2a2a3e; border-color: #333; color: #555; }}
  .no-data {{ color: #555; padding: 4px 8px; font-size: 11px; }}

  /* Ticket GGUS */
  .tickets-section h3 {{ font-size: 12px; color: #888; margin: 10px 0 6px; border-top: 1px solid #333; padding-top: 8px; }}
  .ticket {{ background: #16213e; border: 1px solid #0f3460; border-radius: 4px;
              padding: 8px 12px; margin-bottom: 8px; }}
  .ticket-header {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 4px; }}
  .ticket-id   {{ font-weight: bold; color: #a8d8ea; }}
  .ticket-id a {{ color: inherit; }}
  .ticket-title {{ color: #e0e0e0; }}
  .ticket-meta  {{ font-size: 11px; color: #777; }}
  .ticket-body  {{ font-size: 11px; color: #aaa; margin-top: 6px; white-space: pre-wrap;
                   max-height: 120px; overflow: hidden; border-left: 2px solid #0f3460;
                   padding-left: 8px; }}
  .ticket-new  {{ border-left: 3px solid #FF6633; }}
  .ticket-week {{ border-left: 3px solid #FFAA33; }}
  .ticket-old  {{ border-left: 3px solid #888; }}

  .no-tickets {{ color: #555; font-size: 11px; padding: 4px 0; }}

  .vo-badge {{ font-size: 10px; font-weight: bold; padding: 1px 6px;
               border-radius: 3px; flex-shrink: 0; }}
  .vo-cms  {{ background: #1a5276; color: #85c1e9; border: 1px solid #2980b9; }}
  .vo-wlcg {{ background: #1e3a1e; color: #82e0aa; border: 1px solid #239b56; }}

  details.old-tickets {{ margin-top: 6px; }}
  details.old-tickets summary {{
    cursor: pointer; color: #888; font-size: 11px;
    padding: 4px 8px; background: #1a1a2e; border-radius: 4px;
    list-style: none; user-select: none;
  }}
  details.old-tickets summary:hover {{ color: #aaa; }}

  .tier-separator {{
    margin: 24px 0 10px; padding: 6px 12px;
    background: #0a1628; border-left: 3px solid #a8d8ea;
    color: #a8d8ea; font-size: 13px; font-weight: bold; border-radius: 0 4px 4px 0;
  }}
</style>
</head>
<body>

<h1>&#9888; CMS SST — Sites with Problems</h1>
<div class="subtitle">Generated: {now_str} &nbsp;|&nbsp; Metric window: last {problem_days} days &nbsp;|&nbsp;
  Source: <a href="{REPORT_URL}" target="_blank" style="color:#a8d8ea">sitereadiness/report.html</a> +
  <a href="https://helpdesk.ggus.eu" target="_blank" style="color:#a8d8ea">GGUS</a>
</div>

<div class="summary">
  <span>Sites with errors: <span class="badge-err">{n_problems}</span></span>
  <span>Total sites: {len(sites_data)}</span>
</div>

<p style="color:#888;font-size:11px;margin-bottom:16px">
  Metric columns = last {problem_days} days (oldest to most recent, left to right).<br>
  Click a cell to open the detailed SAM/HC/FTS log. Click a site name for the full readiness report.
</p>
"""

    col_headers = "".join(
        f"<th>-{problem_days - i}d</th>" for i in range(problem_days)
    )

    current_tier = None
    for site_name, data in site_list:
        sev = data["max_severity"]
        sev_label, sev_color = severity_label(sev)
        tickets = ggus_by_site.get(site_name, [])
        n_tickets = len(tickets)

        tier = re.match(r"T(\d)", site_name)
        tier_str = f"Tier-{tier.group(1)}" if tier else ""
        this_tier = tier.group(1) if tier else "?"

        if this_tier != current_tier:
            current_tier = this_tier
            html_out += f'<div class="tier-separator">Tier-{current_tier}</div>\n'
        summary_url = f"https://cmssst.web.cern.ch/siteStatus/summary.html#{site_name}"
        report_anchor = f"https://cmssst.web.cern.ch/sitereadiness/report.html#{site_name}"

        html_out += f"""
<div class="site-block">
  <div class="site-header">
    <div class="site-name">
      <a href="{summary_url}" target="_blank">{site_name}</a>
    </div>
    <span class="site-tier">{tier_str}</span>
    <span class="sev-badge" style="background:{sev_color};color:#fff">{sev_label}</span>
    <span class="ticket-count">{'&#128190; ' + str(n_tickets) + (' ticket' if n_tickets == 1 else ' tickets') if n_tickets else ''}</span>
  </div>
  <div class="site-body">
    <table class="metrics-table">
      <tr><td></td>{col_headers}</tr>
      <tr>{metric_html(data["SAM"], "SAM")}</tr>
      <tr>{metric_html(data["HC"], "HammerCloud")}</tr>
      <tr>{metric_html(data["FTS"], "FTS")}</tr>
    </table>
"""

        # Tickets section — sort by date desc, group old ones (>90 days)
        html_out += '<div class="tickets-section">'
        if tickets:
            # ordine: CMS VO prima, poi WLCG; dentro ogni gruppo: data decrescente
            # Con reverse=True: (1, "2026-03-20") > (0, ...) → CMS (1) viene prima
            def ticket_sort_key(t):
                return (1 if t.get("is_cms") else 0, t["created_at"])
            tickets_sorted = sorted(tickets, key=ticket_sort_key, reverse=True)
            recent = [t for t in tickets_sorted if days_ago(t["created_at"]) <= 90]
            old    = [t for t in tickets_sorted if days_ago(t["created_at"]) > 90]

            html_out += (
                f'<h3>Open GGUS tickets ({n_tickets}) — '
                f'<a href="{report_anchor}" target="_blank" style="color:#888">full report</a></h3>'
            )

            def render_ticket(t):
                age_class = ticket_age_class(t["created_at"])
                t_url     = GGUS_TICKET_URL.format(id=t["id"])
                created   = t["created_at"][:10]
                updated   = t["updated_at"][:10]
                days_open = days_ago(t["created_at"])
                body_safe = html.escape(t["body"]) if t["body"] else ""
                body_html = f'<div class="ticket-body">{body_safe}</div>' if body_safe else ""
                if t.get("is_cms"):
                    vo_badge = '<span class="vo-badge vo-cms">CMS</span>'
                else:
                    vo_badge = '<span class="vo-badge vo-wlcg">WLCG</span>'
                return f"""
    <div class="ticket {age_class}">
      <div class="ticket-header">
        {vo_badge}
        <span class="ticket-id"><a href="{t_url}" target="_blank">#{t["number"]} (id:{t["id"]})</a></span>
        <span class="ticket-title">{html.escape(t["title"])}</span>
      </div>
      <div class="ticket-meta">
        State: <b>{t["state"]}</b> &nbsp;|&nbsp;
        Priority: {t["priority"]} &nbsp;|&nbsp;
        Opened: {created} ({days_open}d ago) &nbsp;|&nbsp;
        Updated: {updated}
      </div>
      {body_html}
    </div>"""

            for t in recent:
                html_out += render_ticket(t)

            if old:
                old_id = f"old_{site_name.replace(' ', '_')}"
                html_out += f"""
    <details class="old-tickets">
      <summary>&#9660; {len(old)} ticket{'s' if len(old) != 1 else ''} older than 90 days</summary>"""
                for t in old:
                    html_out += render_ticket(t)
                html_out += "\n    </details>"
        else:
            html_out += '<p class="no-tickets">No open GGUS tickets</p>'

        html_out += "</div></div></div>\n"

    html_out += """
<div style="margin-top:30px;font-size:11px;color:#555;border-top:1px solid #333;padding-top:12px">
  CMS Site Support Team &nbsp;|&nbsp;
  <a href="https://cmssst.web.cern.ch/siteStatus/summary.html" style="color:#888">Status Summary</a> &nbsp;|&nbsp;
  <a href="https://cmssst.web.cern.ch/sitereadiness/report.html" style="color:#888">SR Report</a> &nbsp;|&nbsp;
  <a href="https://helpdesk.ggus.eu" style="color:#888">GGUS</a>
</div>
</body>
</html>"""

    return html_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="CMS SST Daily Problem Report")
    parser.add_argument("--token", default="documentation/token_ggus",
                        help="File con il Bearer token GGUS")
    parser.add_argument("--days", type=int, default=3,
                        help="Look-back window in days (default: 3)")
    parser.add_argument("--out", default="cms_report.html",
                        help="File HTML di output (default: cms_report.html)")
    parser.add_argument("--all", action="store_true", dest="show_all",
                        help="Include all sites, even those without problems")
    args = parser.parse_args()

    # --- Token: file > env var GGUS_TOKEN ---
    import os
    token_path = Path(args.token)
    if token_path.exists():
        token = token_path.read_text().strip()
    elif os.environ.get("GGUS_TOKEN"):
        token = os.environ["GGUS_TOKEN"].strip()
        print("Using token from GGUS_TOKEN env var", file=sys.stderr)
    else:
        print(f"[ERROR] Token not found: set --token FILE or GGUS_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    # --- Fetch report.html ---
    print("Fetching report.html ...", file=sys.stderr)
    try:
        report_content = fetch(REPORT_URL)
    except Exception as e:
        print(f"[ERROR] Impossibile scaricare report.html: {e}", file=sys.stderr)
        sys.exit(1)

    print("Parsing metrics ...", file=sys.stderr)
    sites_data = parse_report(report_content, problem_days=args.days)
    print(f"  {len(sites_data)} sites found", file=sys.stderr)

    # --- Fetch GGUS tickets ---
    print("Fetching GGUS tickets ...", file=sys.stderr)
    try:
        ggus_by_site = fetch_ggus_tickets(token)
        total_tickets = sum(len(v) for v in ggus_by_site.values())
        print(f"  {total_tickets} open tickets across {len(ggus_by_site)} sites", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] GGUS fetch failed: {e}. Continuing without tickets.", file=sys.stderr)
        ggus_by_site = {}

    # --- Genera HTML ---
    print("Generating report ...", file=sys.stderr)
    out_html = generate_html(sites_data, ggus_by_site, args.days, args.show_all)

    out_path = Path(args.out)
    out_path.write_text(out_html, encoding="utf-8")
    print(f"Report saved: {out_path.resolve()}", file=sys.stderr)

    # Stampa sommario a terminale
    problem_sites = [
        (s, d) for s, d in sites_data.items()
        if d["max_severity"] >= 3 and not s.startswith("T2_RU_")
    ]
    problem_sites.sort(key=lambda x: (int(re.match(r"T(\d)", x[0]).group(1)), x[0]))
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Sites in ERROR: {len(problem_sites)} / {len(sites_data)}", file=sys.stderr)
    for site, data in problem_sites:
        sev_lbl, _ = severity_label(data["max_severity"])
        n_t = len(ggus_by_site.get(site, []))
        ticket_str = f" | {n_t} ticket{'s' if n_t != 1 else ''}" if n_t else ""
        print(f"  {site:<32} {sev_lbl:<12}{ticket_str}", file=sys.stderr)


if __name__ == "__main__":
    main()

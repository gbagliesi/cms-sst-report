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

Token resolution order: --token file > GGUS_TOKEN environment variable
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
MAX_DAYS = 7   # maximum days parsed and embedded in the report
ARTICLE_CACHE = Path("documentation/ggus_article_cache.json")

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

# SSB badge: the 4 CMS SSB administrative site states and their display colors.
# Colors match the CERN cmssst.web.cern.ch color scheme.
SSB_BADGE_COLORS = {
    "ok":           (COLOR_OK,       "#1a3a1a"),   # green  — site in production
    "waiting_room": ("#A000A0",      "#ffffff"),   # purple — site not yet in production (WR)
    "morgue":       ("#663300",      "#ffffff"),   # brown  — site decommissioned
    "downtime":     (COLOR_DOWNTIME, "#ffffff"),   # blue   — scheduled downtime
}
SSB_BADGE_LABELS = {
    "ok":           "ok",
    "waiting_room": "waiting room",
    "morgue":       "morgue",
    "downtime":     "downtime",
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
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r" +", " ", text).strip()


def linkify(text):
    """Escape text for HTML and turn URLs into clickable links."""
    url_re = re.compile(r"(https?://\S+)")
    parts = url_re.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            esc = html.escape(part)
            out.append(f'<a href="{esc}" target="_blank" style="color:#2471a3">{esc}</a>')
        else:
            out.append(html.escape(part))
    return "".join(out)


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
def parse_report(content, problem_days=MAX_DAYS):
    """
    Returns dict: {site_name: {
        'dates':    [str, ...],        # last problem_days dates (most recent = last)
        'SAM':      [{color, pct, tooltip, log_url}, ...],
        'HC':       [{color, pct, tooltip, log_url}, ...],
        'FTS':      [{color, pct, tooltip, log_url}, ...],
        'ggus_old': [ticket_id, ...],  # GGUS tickets from legacy system (ggus.eu)
        'max_severity': int,
    }}
    """

    # Normalize whitespace
    content = re.sub(r"\s+", " ", content)

    # --- Extract site information block by block ---
    # Each site starts with: <A NAME="T?_...">sitename</A>
    site_blocks = re.split(r'<A NAME="(T\d_[A-Z]{2}_\w+)">', content)
    # site_blocks[0] = content before first site
    # then pairs: site_name, block_content

    sites = {}
    i = 1
    while i < len(site_blocks) - 1:
        site_name = site_blocks[i]
        block = site_blocks[i + 1]
        i += 2

        # Truncate block at the next site anchor
        next_site = block.find('<A NAME="T')
        if next_site > 0:
            block = block[:next_site]

        site_data = {
            "dates":      [],
            "SAM":        [],
            "HC":         [],
            "FTS":        [],
            "ggus_old":   [],
            "max_severity": 0,
            "ssb_status": None,
            "ssb_color":  "",
        }

        # --- Legacy GGUS tickets (ggus.eu links) ---
        for tid in re.findall(
            r'ggus\.eu/\?mode=ticket_info&ticket_id=(\d+)', block
        ):
            site_data["ggus_old"].append(tid)

        # --- Metric rows ---
        # Cell pattern with tooltip:
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

        # Simpler approach: find each row by label
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
            # Keep only the last MAX_DAYS cells (most recent)
            cells = cells[-MAX_DAYS:]
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

        # --- SSB administrative state (ok / waiting_room / morgue / downtime) ---
        # "Life Status:" row uses tdCell1 cells (no link), with text "WR" or "M".
        # Colors: #A000A0 = Waiting Room, #663300 = Morgue, #6080FF = downtime, #80FF80 = ok.
        cell1_pat = re.compile(
            r'<TD[^>]+CLASS="tdCell1"[^>]*background-color:\s*(#[0-9A-Fa-f]{6})[^>]*>([^<]*)',
            re.IGNORECASE,
        )

        ssb = "ok"  # default: site is in production

        ls_idx = block.find("Life Status:")
        if ls_idx >= 0:
            row_end = block.find("<TR", ls_idx + 10)
            row_html = block[ls_idx:row_end] if row_end > 0 else block[ls_idx:ls_idx + 4000]
            ls_cells = cell1_pat.findall(row_html)
            if ls_cells:
                # Most recent cell (last in the row)
                last_color, last_text = ls_cells[-1][0].upper(), ls_cells[-1][1].strip()
                if last_color == "#A000A0" or last_text == "WR":
                    ssb = "waiting_room"
                elif last_color == "#663300" or last_text == "M":
                    ssb = "morgue"
                elif last_color == COLOR_DOWNTIME.upper():
                    ssb = "downtime"

        site_data["ssb_status"] = ssb
        site_data["ssb_color"]  = SSB_BADGE_COLORS.get(ssb, ("", ""))[0]

        sites[site_name] = site_data

    return sites


# ---------------------------------------------------------------------------
# Article cache helpers
# ---------------------------------------------------------------------------
def load_article_cache():
    if ARTICLE_CACHE.exists():
        try:
            return json.loads(ARTICLE_CACHE.read_text())
        except Exception:
            pass
    return {}


def save_article_cache(cache):
    try:
        ARTICLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        ARTICLE_CACHE.write_text(json.dumps(cache, separators=(",", ":")))
    except Exception as e:
        print(f"[WARN] Could not save article cache: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Fetch GGUS tickets
# ---------------------------------------------------------------------------
def fetch_ggus_tickets(token, art_cache=None, max_batches=64):
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

    # Group by CMS site
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
            continue  # skip tickets with no identifiable CMS site

        # Fetch all articles (use cache to avoid re-fetching)
        if art_cache is None:
            art_cache = {}
        articles = []
        for art_id in t.get("article_ids", []):
            key = str(art_id)
            if key in art_cache:
                articles.append(art_cache[key])
                continue
            try:
                art = json.loads(fetch(f"{GGUS_API}/ticket_articles/{art_id}", headers))
                entry = {
                    "from":       art.get("from", ""),
                    "created_at": (art.get("created_at") or "")[:19].replace("T", " "),
                    "body":       html.unescape(strip_tags(art.get("body", "")))[:2000],
                }
                articles.append(entry)
                art_cache[key] = entry
            except Exception:
                pass
        # first article body (for backward compat / summary display)
        body = articles[0]["body"] if articles else ""

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
            "articles":   articles,
            "is_cms":     is_cms,
        }
        by_site.setdefault(cms_site, []).append(entry)

    return by_site


# ---------------------------------------------------------------------------
# Generate HTML report
# ---------------------------------------------------------------------------
def severity_label(sev):
    """Return (label, bg_color, text_color) using SSB standard colors."""
    if sev >= 3: return ("error",   COLOR_ERROR,   "#ffffff")
    if sev >= 2: return ("partial", COLOR_PDTIME,  "#ffffff")
    if sev >= 1: return ("warning", COLOR_WARNING, "#333333")
    return ("ok",    COLOR_OK,      "#1a3a1a")


def metric_html(cells, metric_name):
    # didx: 1 = most recent, MAX_DAYS = oldest
    # cells list is ordered oldest→newest, so cells[-1] = most recent = didx 1
    n = len(cells)
    if not cells:
        # emit MAX_DAYS hidden placeholder cells so column count stays consistent
        out = f"<td class='metric-name'>{metric_name}</td>"
        out += f"<td class='no-data dcol' data-didx='1' colspan='{MAX_DAYS}'>— no data —</td>"
        return out

    out = f"<td class='metric-name'>{metric_name}</td>"
    # pad oldest slots with empty cells up to MAX_DAYS total
    for pad_idx in range(MAX_DAYS - n, 0, -1):
        didx = MAX_DAYS - (MAX_DAYS - n - pad_idx) - pad_idx + 1
        # simpler: padded cells at the left get the highest didx values
        real_didx = pad_idx + n   # e.g. if n=3 and MAX_DAYS=7, pads get didx 7,6,5,4
        out += f"<td class='metric-cell empty dcol' data-didx='{real_didx}'>&mdash;</td>"
    for i, cell in enumerate(cells):
        # cells[0]=oldest, cells[-1]=most recent
        didx = n - i          # cells[0] → didx=n, cells[-1] → didx=1
        bg = cell["color"] or "#F4F4F4"
        pct = cell["pct"] or "?"
        tooltip = cell["tooltip"].replace('"', "&quot;")
        log = cell.get("log_url", "#")
        status = cell.get("status", "unknown")
        out += (
            f'<td class="metric-cell dcol" data-didx="{didx}" data-status="{status}" style="background:{bg}" title="{tooltip}">'
            f'<a href="{log}" target="_blank">{pct}</a></td>'
        )
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

    def is_excluded(site):
        # Exclude decommissioned T2_RU_* sites, but keep T2_RU_JINR (still active)
        return site.startswith("T2_RU_") and site != "T2_RU_JINR"

    # Always generate ALL non-excluded sites; client-side JS controls visibility
    site_list = sorted(
        [(s, d) for s, d in sites_data.items() if not is_excluded(s)],
        key=lambda kv: (tier_num(kv[0]), kv[0])
    )

    n_total  = len(site_list)
    n_errors = sum(1 for s, d in site_list if d["max_severity"] >= 3)

    # --- CSS + HTML ---
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMS SST Daily Report — {now_str}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: monospace; font-size: 13px; background: #f0f4f8; color: #222; margin: 0; padding: 16px; }}
  h1   {{ color: #1a4a6e; font-size: 18px; margin-bottom: 4px; }}
  .subtitle {{ color: #555; font-size: 12px; margin-bottom: 24px; }}
  .summary {{ background: #ffffff; border: 1px solid #c0d0e0; border-radius: 6px;
              padding: 10px 16px; margin-bottom: 20px; display: flex; gap: 24px; align-items: center; }}
  .summary span {{ font-size: 13px; }}
  .badge-err  {{ background: #FF4444; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: bold; }}
  .badge-ok   {{ background: #44BB44; color: #fff; padding: 2px 8px; border-radius: 4px; }}

  .site-block {{ border: 1px solid #c0d0e0; border-radius: 6px; margin-bottom: 16px;
                 overflow: hidden; }}
  .site-header {{ display: flex; align-items: center; gap: 12px;
                  padding: 8px 14px; background: #1a4a6e; }}
  .site-name   {{ font-size: 15px; font-weight: bold; color: #ffffff; }}
  .site-name a {{ color: inherit; text-decoration: none; }}
  .site-name a:hover {{ text-decoration: underline; }}
  .sev-badge   {{ padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
  .ssb-badge   {{ padding: 1px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;
                  border: 1px solid rgba(0,0,0,0.15); white-space: nowrap; }}
  .site-tier   {{ color: #aaccdd; font-size: 11px; }}
  .full-report-link {{ font-size: 11px; color: #aaccdd; text-decoration: none; }}
  .full-report-link:hover {{ color: #ffffff; text-decoration: underline; }}
  .ticket-count {{ margin-left: auto; font-size: 11px; color: #ffd700; }}

  .site-body   {{ padding: 12px 14px; background: #ffffff; }}

  /* Tabella metriche */
  .metrics-table {{ border-collapse: collapse; margin-bottom: 14px; }}
  .metrics-table th {{ color: #666; font-weight: normal; font-size: 11px;
                       text-align: right; padding: 2px 6px; }}
  .metric-name {{ color: #555; padding: 3px 8px 3px 0; white-space: nowrap; min-width: 110px; }}
  .metric-cell {{ width: 80px; text-align: center; padding: 4px 6px;
                  border: 1px solid #ccc; border-radius: 3px; }}
  .metric-cell a {{ color: #1a1a2e; text-decoration: none; font-weight: bold; font-size: 12px; }}
  .metric-cell.empty {{ background: #e8e8e8; border-color: #ccc; color: #aaa; }}
  .no-data {{ color: #aaa; padding: 4px 8px; font-size: 11px; }}

  /* Ticket GGUS */
  .tickets-section h3 {{ font-size: 12px; color: #666; margin: 10px 0 6px; border-top: 1px solid #ddd; padding-top: 8px; }}
  .ticket {{ background: #f8f9fa; border: 1px solid #c0d0e0; border-radius: 4px;
              padding: 8px 12px; margin-bottom: 8px; }}
  .ticket-header {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 4px; }}
  .ticket-id   {{ font-weight: bold; color: #1a4a6e; }}
  .ticket-id a {{ color: inherit; }}
  .ticket-title {{ color: #222; }}
  .ticket-meta  {{ font-size: 11px; color: #777; }}
  .ticket-body  {{ font-size: 11px; color: #555; margin-top: 6px; white-space: pre-wrap;
                   max-height: 120px; overflow: hidden; border-left: 2px solid #7ab0cc;
                   padding-left: 8px; }}
  .ticket-new  {{ border-left: 3px solid #FF6633; }}
  .ticket-week {{ border-left: 3px solid #FFAA33; }}
  .ticket-old  {{ border-left: 3px solid #aaa; }}

  .no-tickets {{ color: #aaa; font-size: 11px; padding: 4px 0; }}

  .vo-badge {{ font-size: 10px; font-weight: bold; padding: 1px 6px;
               border-radius: 3px; flex-shrink: 0; }}
  .vo-cms  {{ background: #d6eaf8; color: #1a4a6e; border: 1px solid #7ab0cc; }}
  .vo-wlcg {{ background: #d5f5e3; color: #1e5631; border: 1px solid #58d68d; }}

  details.ticket-group {{ margin-top: 6px; }}
  details.ticket-group > summary {{
    cursor: pointer; color: #1a4a6e; font-size: 12px; font-weight: bold;
    padding: 4px 8px; background: #e8f0f8; border-radius: 4px;
    list-style: none; user-select: none; margin-bottom: 4px;
  }}
  details.ticket-group > summary:hover {{ background: #d6e8f5; }}
  details.ticket-group > summary::before {{ content: "▶ "; font-size: 9px; }}
  details.ticket-group[open] > summary::before {{ content: "▼ "; font-size: 9px; }}

  .tier-separator {{
    margin: 24px 0 10px; padding: 6px 12px;
    background: #e8f0f8; border-left: 3px solid #1a4a6e;
    color: #1a4a6e; font-size: 13px; font-weight: bold; border-radius: 0 4px 4px 0;
  }}
  .days-ctrl {{
    display: flex; align-items: center; gap: 10px;
    margin-left: auto;
  }}
  .days-ctrl label {{ color: #555; font-size: 12px; }}
  .days-ctrl select {{
    background: #ffffff; color: #222; border: 1px solid #7ab0cc;
    border-radius: 4px; padding: 3px 8px; font-size: 12px; cursor: pointer;
  }}
  .days-ctrl select:focus {{ outline: none; }}
  .filter-ctrl {{
    display: flex; align-items: center; gap: 6px; margin-left: 16px;
    font-size: 12px; color: #555; cursor: pointer; user-select: none;
  }}
  .filter-ctrl input {{ accent-color: #1a4a6e; cursor: pointer; }}
  .site-block.hidden-by-filter {{ display: none; }}
  .site-block.hidden-by-tier   {{ display: none; }}
  .site-block.hidden-by-search {{ display: none; }}
  .site-search-wrap {{ display:flex; align-items:center; gap:6px; }}
  #site-search {{
    padding: 3px 8px; border: 1px solid #1a4a6e; border-radius: 4px;
    font-size: 13px; width: 200px; background:#fff; color:#1a1a2e;
  }}
  #site-search:focus {{ outline: 2px solid #1a4a6e; }}
  #search-hint {{ font-size: 12px; color: #888; font-style: italic; }}
  .tier-ctrl {{
    display: flex; align-items: center; gap: 10px; margin-left: 16px;
    font-size: 12px; color: #555;
  }}
  .tier-ctrl span {{ color: #666; }}
  .tier-btn {{
    display: inline-flex; align-items: center; gap: 4px;
    cursor: pointer; user-select: none;
  }}
  .tier-btn input {{ accent-color: #1a4a6e; cursor: pointer; }}

  /* Ticket conversation */
  details.ticket-conv {{ margin-top: 6px; }}
  details.ticket-conv > summary {{
    cursor: pointer; font-size: 11px; color: #2471a3; list-style: none;
    padding: 2px 0; user-select: none;
  }}
  details.ticket-conv > summary:hover {{ color: #1a4a6e; }}
  details.ticket-conv > summary::before {{ content: "▶ "; font-size: 9px; }}
  details.ticket-conv[open] > summary::before {{ content: "▼ "; font-size: 9px; }}
  .conv-article {{ margin-top: 8px; padding: 6px 10px; background: #e8f4ff;
                   border-left: 2px solid #7ab0cc; border-radius: 0 4px 4px 0; }}
  .conv-article-meta {{ font-size: 10px; color: #888; margin-bottom: 4px; }}
  .conv-article-body {{ font-size: 11px; color: #444; white-space: pre-wrap;
                        max-height: 200px; overflow-y: auto; }}

  /* Ticket drawer */
  #drawer-overlay {{
    display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.25); z-index: 1000;
  }}
  #drawer-overlay.open {{ display: block; }}
  #ticket-drawer {{
    position: fixed; top: 0; right: 0; width: 44%; height: 100%;
    background: #f0f4f8; border-left: 2px solid #1a4a6e;
    z-index: 1001; transform: translateX(100%);
    transition: transform 0.25s ease;
    display: flex; flex-direction: column; overflow: hidden;
  }}
  #ticket-drawer.open {{ transform: translateX(0); }}
  #drawer-header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 16px; background: #1a4a6e; color: #fff; flex-shrink: 0;
  }}
  #drawer-title {{ font-size: 13px; font-weight: bold; }}
  #drawer-close {{
    background: none; border: none; color: #fff; font-size: 22px;
    cursor: pointer; padding: 0 4px; line-height: 1;
  }}
  #drawer-body {{ flex: 1; overflow-y: auto; padding: 14px; }}
  .tstat-link {{
    cursor: pointer; text-decoration: underline dotted; color: inherit;
  }}
  .tstat-link:hover {{ color: #ffffff; }}
</style>
<script>
function applyFilters() {{
  var n       = parseInt(document.getElementById('days-sel').value);
  var chkErr  = document.getElementById('filter-errors').checked;
  var chkOk   = document.getElementById('filter-ok').checked;
  var ssbFilter = document.getElementById('ssb-sel').value;
  var search  = document.getElementById('site-search').value.trim().toLowerCase();
  var searchActive = search.length >= 3;

  // search hint
  var hint = document.getElementById('search-hint');
  if (hint) {{
    if (search.length > 0 && search.length < 3) {{
      hint.textContent = 'min. 3 characters'; hint.style.display = '';
    }} else {{
      hint.style.display = 'none';
    }}
  }}

  // which tiers are selected
  var activeTiers = {{}};
  document.querySelectorAll('.tier-chk').forEach(function(cb) {{
    activeTiers[cb.value] = cb.checked;
  }});

  // show/hide metric columns and headers
  document.querySelectorAll('.dcol').forEach(function(el) {{
    el.style.display = parseInt(el.getAttribute('data-didx')) <= n ? '' : 'none';
  }});
  document.querySelectorAll('.dth').forEach(function(th) {{
    var d = parseInt(th.getAttribute('data-didx'));
    th.style.display = d <= n ? '' : 'none';
    if (d <= n) th.textContent = '-' + d + 'd';
  }});
  var lbl = document.getElementById('days-label');
  if (lbl) lbl.textContent = n + ' day' + (n > 1 ? 's' : '');

  var shownCount = 0;
  var shownErrors = 0;

  // show/hide site blocks
  document.querySelectorAll('.site-block').forEach(function(block) {{
    var hasError = false;
    block.querySelectorAll('.dcol[data-status]').forEach(function(cell) {{
      if (parseInt(cell.getAttribute('data-didx')) <= n &&
          cell.getAttribute('data-status') === 'error') {{
        hasError = true;
      }}
    }});

    var ssbOk = (ssbFilter === 'all') || (block.getAttribute('data-ssb') === ssbFilter);
    block.classList.toggle('hidden-by-ssb', !ssbOk);

    if (searchActive) {{
      // search mode: ignore tier/error/ssb filters, match by site name
      var siteName = (block.getAttribute('data-site') || '').toLowerCase();
      var match = siteName.includes(search);
      block.classList.toggle('hidden-by-search', !match);
      block.classList.remove('hidden-by-tier');
      block.classList.remove('hidden-by-filter');
      block.classList.remove('hidden-by-ssb');
      if (match) {{ shownCount++; if (hasError) shownErrors++; }}
    }} else {{
      // normal mode
      block.classList.remove('hidden-by-search');
      var tier = block.getAttribute('data-tier');
      var tierOk = activeTiers[tier];
      block.classList.toggle('hidden-by-tier', !tierOk);
      var passFilter;
      if (!chkErr && !chkOk) {{
        passFilter = true;
      }} else {{
        passFilter = (chkErr && hasError) || (chkOk && !hasError);
      }}
      block.classList.toggle('hidden-by-filter', !passFilter);
      if (tierOk && passFilter && ssbOk) {{ shownCount++; if (hasError) shownErrors++; }}
    }}
  }});

  // hide tier separators
  document.querySelectorAll('.tier-separator').forEach(function(sep) {{
    if (searchActive) {{ sep.style.display = 'none'; return; }}
    var next = sep.nextElementSibling;
    var anyVisible = false;
    while (next && !next.classList.contains('tier-separator')) {{
      if (next.classList.contains('site-block') &&
          !next.classList.contains('hidden-by-filter') &&
          !next.classList.contains('hidden-by-tier') &&
          !next.classList.contains('hidden-by-ssb')) {{
        anyVisible = true; break;
      }}
      next = next.nextElementSibling;
    }}
    sep.style.display = anyVisible ? '' : 'none';
  }});

  // total count
  var tierCount;
  if (searchActive) {{
    tierCount = shownCount;
  }} else {{
    tierCount = 0;
    document.querySelectorAll('.site-block').forEach(function(block) {{
      if (activeTiers[block.getAttribute('data-tier')]) tierCount++;
    }});
  }}

  // update counters
  var elShown  = document.getElementById('cnt-shown');
  var elErr    = document.getElementById('cnt-err');
  var elTotal  = document.getElementById('cnt-total');
  if (elShown) elShown.textContent = shownCount;
  if (elErr)   elErr.textContent   = shownErrors;
  if (elTotal) elTotal.textContent = tierCount;
}}

function doRefresh() {{
  var btn = document.getElementById('refresh-btn');
  var isLocal = window.location.hostname === 'localhost' ||
                window.location.hostname === '127.0.0.1';
  if (isLocal) {{
    btn.textContent = '⟳';
    btn.title = 'Refreshing...';
    btn.disabled = true;
    fetch('/refresh')
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d.status === 'ok') {{ location.reload(); }}
        else {{
          btn.disabled = false;
          btn.title = 'Error — check terminal';
          btn.textContent = '⟳';
        }}
      }})
      .catch(function() {{
        btn.disabled = false;
        btn.title = 'Server not reachable (run cms_local_server.py)';
      }});
  }} else {{
    window.open('https://github.com/gbagliesi/cms-sst-report/actions', '_blank');
  }}
}}

window.addEventListener('DOMContentLoaded', function() {{
  document.getElementById('days-sel').addEventListener('change', applyFilters);
  document.getElementById('filter-errors').addEventListener('change', applyFilters);
  document.getElementById('filter-ok').addEventListener('change', applyFilters);
  document.getElementById('ssb-sel').addEventListener('change', applyFilters);
  document.getElementById('site-search').addEventListener('input', applyFilters);
  document.querySelectorAll('.tier-chk').forEach(function(cb) {{
    cb.addEventListener('change', applyFilters);
  }});
  applyFilters();
}});

// --- Ticket Drawer ---
function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function linkifyText(raw) {{
  var urlRe = /(https?:[/][/][^\\s]+)/g;
  var parts = String(raw).split(urlRe);
  return parts.map(function(part, i) {{
    if (i % 2 === 1) {{
      var esc = escHtml(part);
      return '<a href="' + esc + '" target="_blank" style="color:#2471a3">' + esc + '</a>';
    }}
    return escHtml(part);
  }}).join('');
}}

function renderDrawerTicket(t) {{
  var ageClass = t.days_open > 30 ? 'ticket-old' : (t.days_open > 7 ? 'ticket-week' : 'ticket-new');
  var voBadge = t.is_cms
    ? '<span class="vo-badge vo-cms">CMS</span>'
    : '<span class="vo-badge vo-wlcg">WLCG</span>';
  var tUrl = 'https://helpdesk.ggus.eu/#ticket/zoom/' + t.id;
  var openedHtml = t.days_open > 90
    ? '<span style="color:#cc4400;font-weight:bold">' + escHtml(t.created_at) + ' (' + t.days_open + 'd ago)</span>'
    : escHtml(t.created_at) + ' (' + t.days_open + 'd ago)';
  var convHtml = '';
  if (t.articles && t.articles.length) {{
    var nArt = t.articles.length;
    var parts = t.articles.map(function(art, i) {{
      var label = i === 0 ? 'Initial report' : 'Reply ' + i;
      return '<div class="conv-article">'
        + '<div class="conv-article-meta">#' + (i+1) + ' ' + label
        + ' &nbsp;|&nbsp; ' + escHtml(art.from)
        + ' &nbsp;|&nbsp; ' + escHtml(art.created_at) + '</div>'
        + '<div class="conv-article-body">' + linkifyText(art.body) + '</div>'
        + '</div>';
    }});
    convHtml = '<details class="ticket-conv"><summary>Conversation ('
      + nArt + ' message' + (nArt !== 1 ? 's' : '') + ')</summary>'
      + parts.join('') + '</details>';
  }}
  return '<div class="ticket ' + ageClass + '">'
    + '<div class="ticket-header">' + voBadge
    + ' <span class="ticket-id"><a href="' + tUrl + '" target="_blank">#'
    + escHtml(String(t.number)) + ' (id:' + t.id + ')</a></span>'
    + ' <span class="ticket-title">' + escHtml(t.title) + '</span></div>'
    + '<div class="ticket-meta">State: <b>' + escHtml(t.state) + '</b>'
    + ' &nbsp;|&nbsp; Priority: ' + escHtml(t.priority)
    + ' &nbsp;|&nbsp; Opened: ' + openedHtml
    + ' &nbsp;|&nbsp; Updated: ' + escHtml(t.updated_at) + '</div>'
    + convHtml + '</div>';
}}

function openDrawer(siteName, filter) {{
  var tickets = (window.TICKET_DATA && window.TICKET_DATA[siteName]) || [];
  var filtered;
  if      (filter === 'cms')  filtered = tickets.filter(function(t) {{ return t.is_cms; }});
  else if (filter === 'wlcg') filtered = tickets.filter(function(t) {{ return !t.is_cms; }});
  else if (filter === 'old')  filtered = tickets.filter(function(t) {{ return t.days_open > 90; }});
  else                        filtered = tickets.slice();
  filtered.sort(function(a, b) {{ return b.created_at < a.created_at ? -1 : b.created_at > a.created_at ? 1 : 0; }});
  var labels = {{ all:'All', cms:'CMS', wlcg:'WLCG', old:'Old >3mo' }};
  document.getElementById('drawer-title').textContent =
    siteName + ' — ' + (labels[filter] || filter) + ' tickets (' + filtered.length + ')';
  document.getElementById('drawer-body').innerHTML = filtered.length
    ? filtered.map(renderDrawerTicket).join('')
    : '<p class="no-tickets">No tickets in this filter.</p>';
  document.getElementById('ticket-drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
}}

function closeDrawer() {{
  document.getElementById('ticket-drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeDrawer();
}});
</script>
</head>
<body>

<h1>&#9888; CMS SST — Daily Site Report</h1>
<div class="subtitle" style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;">
  <span>Generated: {now_str} &nbsp;|&nbsp;
    Source: <a href="https://cmssst.web.cern.ch/siteStatus/summary.html" target="_blank" style="color:#1a4a6e">siteStatus/summary.html</a> +
    <a href="https://helpdesk.ggus.eu" target="_blank" style="color:#1a4a6e">GGUS</a>
  </span>
  <button id="refresh-btn" onclick="doRefresh()" title="Refresh data (local) or open GitHub Actions (GitHub Pages)"
    style="background:#ffffff;color:#1a4a6e;border:1px solid #1a4a6e;border-radius:4px;
           padding:2px 10px;cursor:pointer;font-size:14px;margin-left:4px;">&#8635;</button>
  <div class="days-ctrl">
    <label>Window:</label>
    <select id="days-sel">
      {''.join(f'<option value="{d}"{" selected" if d == problem_days else ""}>{d} day{"s" if d > 1 else ""}</option>' for d in range(1, MAX_DAYS + 1))}
    </select>
  </div>
  <label class="filter-ctrl">
    <input type="checkbox" id="filter-errors" checked>
    Show sites with errors in window
  </label>
  <label class="filter-ctrl">
    <input type="checkbox" id="filter-ok">
    Show OK sites in window
  </label>
  <div class="tier-ctrl">
    <span>Tier:</span>
    <label class="tier-btn"><input class="tier-chk" type="checkbox" value="1" checked> T1</label>
    <label class="tier-btn"><input class="tier-chk" type="checkbox" value="2" checked> T2</label>
    <label class="tier-btn"><input class="tier-chk" type="checkbox" value="3" checked> T3</label>
  </div>
  <div class="days-ctrl">
    <label>SSB:</label>
    <select id="ssb-sel">
      <option value="all">all states</option>
      <option value="ok">ok</option>
      <option value="waiting_room">WR</option>
      <option value="morgue">morgue</option>
    </select>
  </div>
  <div class="site-search-wrap">
    <input type="text" id="site-search" placeholder="&#128269; Search site..." autocomplete="off" spellcheck="false">
    <span id="search-hint" style="display:none"></span>
  </div>
</div>

<div class="summary">
  <span>Shown: <span class="badge-err" id="cnt-shown">{n_errors}</span></span>
  <span>&#128308; With errors: <span id="cnt-err">{n_errors}</span></span>
  <span>Total selected sites: <span id="cnt-total">{n_total}</span></span>
</div>

<p style="color:#666;font-size:11px;margin-bottom:16px">
  Metric columns = last <span id="days-label">{problem_days} days</span> (oldest &#8594; most recent).<br>
  Click a cell for the SAM/HC/FTS log. Click a site name for the full readiness report.
  &#8635; refreshes data locally or opens GitHub Actions on the public page.
</p>
"""

    # Build ticket data for JS drawer
    ticket_js_data = {}
    for sn, _ in site_list:
        ts = ggus_by_site.get(sn, [])
        if ts:
            ticket_js_data[sn] = [{
                "id":         t["id"],
                "number":     t.get("number", ""),
                "title":      t.get("title", ""),
                "state":      t.get("state", ""),
                "priority":   t.get("priority", ""),
                "created_at": t.get("created_at", "")[:10],
                "updated_at": t.get("updated_at", "")[:10],
                "days_open":  days_ago(t.get("created_at", "")),
                "is_cms":     t.get("is_cms", False),
                "articles": [
                    {"from": a.get("from", ""), "created_at": a.get("created_at", "")[:16], "body": a.get("body", "")}
                    for a in t.get("articles", [])
                ],
            } for t in ts]
    html_out += f'<script>window.TICKET_DATA={json.dumps(ticket_js_data, ensure_ascii=False)};</script>\n'

    # Headers: didx 1=most recent … MAX_DAYS=oldest; rendered text updated by JS
    col_headers = "".join(
        f'<th class="dth" data-didx="{didx}">-{didx}d</th>'
        for didx in range(MAX_DAYS, 0, -1)
    )

    current_tier = None
    for site_name, data in site_list:
        sev = data["max_severity"]
        sev_label, sev_color, sev_txt = severity_label(sev)
        tickets = ggus_by_site.get(site_name, [])
        n_tickets = len(tickets)

        tier = re.match(r"T(\d)", site_name)
        tier_str = f"Tier-{tier.group(1)}" if tier else ""
        this_tier = tier.group(1) if tier else "?"

        if this_tier != current_tier:
            current_tier = this_tier
            html_out += f'<div class="tier-separator">Tier-{current_tier}</div>\n'
        summary_url = f"https://cmssst.web.cern.ch/sitereadiness/report.html#{site_name}"
        report_anchor = f"https://cmssst.web.cern.ch/siteStatus/detail.html?site={site_name}"

        n_cms  = sum(1 for t in tickets if t.get("is_cms"))
        n_wlcg = n_tickets - n_cms
        n_old  = sum(1 for t in tickets if days_ago(t["created_at"]) > 90)
        if n_tickets:
            sn_js = site_name.replace("'", "\\'")
            ticket_stat  = f'&#128190; <span class="tstat-link" onclick="openDrawer(\'{sn_js}\',\'all\')">tickets: {n_tickets}</span>'
            if n_cms:  ticket_stat += f', <span class="tstat-link" onclick="openDrawer(\'{sn_js}\',\'cms\')">CMS: {n_cms}</span>'
            if n_wlcg: ticket_stat += f', <span class="tstat-link" onclick="openDrawer(\'{sn_js}\',\'wlcg\')">WLCG: {n_wlcg}</span>'
            if n_old:  ticket_stat += f', <span class="tstat-link" onclick="openDrawer(\'{sn_js}\',\'old\')" style="color:#ffaa66">(old &gt;3mo: {n_old})</span>'
        else:
            ticket_stat = ''

        ssb_status = data.get("ssb_status")
        if ssb_status and ssb_status in SSB_BADGE_COLORS:
            ssb_bg, ssb_fg = SSB_BADGE_COLORS[ssb_status]
            ssb_label = SSB_BADGE_LABELS[ssb_status]
            ssb_badge = (f'<span class="ssb-badge" style="background:{ssb_bg};color:{ssb_fg}"'
                         f' title="SSB site state">SSB: {ssb_label}</span>')
        else:
            ssb_badge = ''

        html_out += f"""
<div class="site-block" data-tier="{this_tier}" data-severity="{sev}" data-site="{site_name}" data-ssb="{ssb_status or 'ok'}">
  <div class="site-header">
    <div class="site-name">
      <a href="{summary_url}" target="_blank">{site_name}</a>
    </div>
    <span class="site-tier">{tier_str}</span>
    <span class="sev-badge" style="background:{sev_color};color:{sev_txt}">{sev_label}</span>
    {ssb_badge}
    <a href="{report_anchor}" target="_blank" class="full-report-link">full report</a>
    <span class="ticket-count">{ticket_stat}</span>
  </div>
  <div class="site-body">
    <table class="metrics-table">
      <tr><td></td>{col_headers}</tr>
      <tr>{metric_html(data["SAM"], "SAM")}</tr>
      <tr>{metric_html(data["HC"], "HammerCloud")}</tr>
      <tr>{metric_html(data["FTS"], "FTS")}</tr>
    </table>
"""

        # Tickets section — CMS tickets expanded, WLCG collapsed
        html_out += '<div class="tickets-section">'
        if tickets:
            # Sort within each group by date descending
            def ticket_sort_key(t):
                return t["created_at"]
            cms_tickets  = sorted([t for t in tickets if t.get("is_cms")],  key=ticket_sort_key, reverse=True)
            wlcg_tickets = sorted([t for t in tickets if not t.get("is_cms")], key=ticket_sort_key, reverse=True)

            html_out += f'<h3>Open GGUS tickets ({n_tickets})</h3>'

            def render_ticket(t):
                age_class = ticket_age_class(t["created_at"])
                t_url     = GGUS_TICKET_URL.format(id=t["id"])
                created   = t["created_at"][:10]
                updated   = t["updated_at"][:10]
                days_open = days_ago(t["created_at"])
                vo_badge  = '<span class="vo-badge vo-cms">CMS</span>' if t.get("is_cms") \
                            else '<span class="vo-badge vo-wlcg">WLCG</span>'
                articles  = t.get("articles", [])
                n_art     = len(articles)
                # Build conversation block
                conv_html = ""
                if articles:
                    parts = []
                    for i, art in enumerate(articles):
                        sender   = html.escape(art.get("from", "unknown"))
                        art_date = art.get("created_at", "")[:16]
                        body_e   = linkify(art.get("body", ""))
                        label    = "Initial report" if i == 0 else f"Reply {i}"
                        parts.append(
                            f'<div class="conv-article">'
                            f'<div class="conv-article-meta">#{i+1} {label} &nbsp;|&nbsp; {sender} &nbsp;|&nbsp; {art_date}</div>'
                            f'<div class="conv-article-body">{body_e}</div>'
                            f'</div>'
                        )
                    conv_inner = "\n".join(parts)
                    conv_html = (
                        f'<details class="ticket-conv">'
                        f'<summary>Conversation ({n_art} message{"s" if n_art != 1 else ""})</summary>'
                        f'{conv_inner}'
                        f'</details>'
                    )
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
        Opened: {'<span style="color:#cc4400;font-weight:bold">' if days_open > 90 else ''}{created} ({days_open}d ago){'</span>' if days_open > 90 else ''} &nbsp;|&nbsp;
        Updated: {updated}
      </div>
      {conv_html}
    </div>"""

            if cms_tickets:
                html_out += f'<details class="ticket-group" open><summary>CMS tickets ({len(cms_tickets)})</summary>'
                for t in cms_tickets:
                    html_out += render_ticket(t)
                html_out += "\n</details>"

            if wlcg_tickets:
                html_out += f'<details class="ticket-group"><summary>WLCG tickets ({len(wlcg_tickets)})</summary>'
                for t in wlcg_tickets:
                    html_out += render_ticket(t)
                html_out += "\n</details>"
        else:
            html_out += '<p class="no-tickets">No open GGUS tickets</p>'

        html_out += "</div></div></div>\n"

    html_out += """
<div style="margin-top:30px;font-size:11px;color:#888;border-top:1px solid #ccc;padding-top:12px">
  CMS Site Support Team &nbsp;|&nbsp;
  <a href="https://cmssst.web.cern.ch/siteStatus/summary.html" style="color:#1a4a6e">Status Summary</a> &nbsp;|&nbsp;
  <a href="https://cmssst.web.cern.ch/sitereadiness/report.html" style="color:#1a4a6e">SR Report</a> &nbsp;|&nbsp;
  <a href="https://helpdesk.ggus.eu" style="color:#1a4a6e">GGUS</a>
</div>

<div id="drawer-overlay" onclick="closeDrawer()"></div>
<div id="ticket-drawer">
  <div id="drawer-header">
    <span id="drawer-title"></span>
    <button id="drawer-close" onclick="closeDrawer()" title="Close (Esc)">&times;</button>
  </div>
  <div id="drawer-body"></div>
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
                        help="File containing the GGUS Bearer token")
    parser.add_argument("--days", type=int, default=3,
                        help=f"Default day window shown in the UI (default: 3, max: {MAX_DAYS})")
    parser.add_argument("--out", default="cms_report.html",
                        help="HTML output file (default: cms_report.html)")
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
        print("[ERROR] Token not found: set --token FILE or GGUS_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    # --- Fetch report.html ---
    print("Fetching report.html ...", file=sys.stderr)
    try:
        report_content = fetch(REPORT_URL)
    except Exception as e:
        print(f"[ERROR] Failed to fetch report.html: {e}", file=sys.stderr)
        sys.exit(1)

    print("Parsing metrics...", file=sys.stderr)
    sites_data = parse_report(report_content)
    print(f"  {len(sites_data)} sites found", file=sys.stderr)

    # --- Fetch GGUS tickets (with article cache) ---
    print("Fetching GGUS tickets ...", file=sys.stderr)
    art_cache = load_article_cache()
    cached_before = len(art_cache)
    try:
        ggus_by_site = fetch_ggus_tickets(token, art_cache=art_cache)
        total_tickets = sum(len(v) for v in ggus_by_site.values())
        new_articles = len(art_cache) - cached_before
        print(f"  {total_tickets} open tickets across {len(ggus_by_site)} sites", file=sys.stderr)
        print(f"  Articles: {new_articles} new fetched, {cached_before} from cache", file=sys.stderr)
        save_article_cache(art_cache)
    except Exception as e:
        print(f"[WARN] GGUS fetch failed: {e}. Continuing without tickets.", file=sys.stderr)
        ggus_by_site = {}

    # --- Generate HTML ---
    print("Generating report...", file=sys.stderr)
    out_html = generate_html(sites_data, ggus_by_site, args.days, args.show_all)

    out_path = Path(args.out)
    out_path.write_text(out_html, encoding="utf-8")
    print(f"Report saved: {out_path.resolve()}", file=sys.stderr)

    # Print terminal summary
    problem_sites = [
        (s, d) for s, d in sites_data.items()
        if d["max_severity"] >= 3 and not (s.startswith("T2_RU_") and s != "T2_RU_JINR")
    ]
    problem_sites.sort(key=lambda x: (int(re.match(r"T(\d)", x[0]).group(1)), x[0]))
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Sites in ERROR : {len(problem_sites)} / {len(sites_data)}", file=sys.stderr)
    for site, data in problem_sites:
        sev_lbl, *_ = severity_label(data["max_severity"])
        n_t = len(ggus_by_site.get(site, []))
        ticket_str = f" | {n_t} ticket{'s' if n_t != 1 else ''}" if n_t else ""
        print(f"  {site:<32} {sev_lbl:<12}{ticket_str}", file=sys.stderr)


if __name__ == "__main__":
    main()

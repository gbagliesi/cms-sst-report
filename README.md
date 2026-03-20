# CMS SST Daily Problem Report

Automated daily report of CMS computing sites with issues, generated from public CERN data sources.

**Live report:** https://gbagliesi.github.io/cms-sst-report/

---

## What it shows

- CMS sites currently in **error** state, grouped by Tier (T1 → T2 → T3)
- SAM / HammerCloud / FTS metric status for the last 3 days
- Open GGUS support tickets per site (CMS VO first, then WLCG)

## Data sources

| Source | URL |
|--------|-----|
| Site Readiness report | https://cmssst.web.cern.ch/sitereadiness/report.html |
| GGUS helpdesk API | https://helpdesk.ggus.eu/api/v1 |

## Usage

```bash
# Generate report locally (requires a GGUS Bearer token)
python3 cms_site_report.py --days 3 --out report.html

# Token can be passed via file or environment variable
GGUS_TOKEN=<token> python3 cms_site_report.py
```

Or double-click `run_report.command` from Finder (macOS).

## Automatic updates

A GitHub Actions workflow runs daily at 07:00 UTC and publishes the updated report to GitHub Pages.

The GGUS token must be stored as a repository secret named `GGUS_TOKEN`.

## Excluded sites

- `T2_RU_*` — being decommissioned

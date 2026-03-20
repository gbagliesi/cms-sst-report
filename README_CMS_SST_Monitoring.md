# CMS Site Support Team — Monitoring Infrastructure

> Knowledge base for developing tools related to the monitoring page
> https://cmssst.web.cern.ch/siteStatus/summary.html
>
> **Sources:**
> - Official TWiki: `CMS/SiteSupportSiteStatusSiteReadiness` (r27, 2024-10-02, S.Lammel)
> - Code repository: https://github.com/CMSCompOps/MonitoringScripts

---

## 1. Overview

The system monitors the operational status of all CMS computing sites (Tier-0, Tier-1, Tier-2, Tier-3) in the WLCG.

**Three primary inputs:**
1. **SAM Tests** — availability of CE, SRM, WebDAV, XRootD services
2. **HammerCloud Tests** — HTCondor/CRAB job success rate
3. **FTS Transfer Results** — file transfer quality (underlying PhEDEx/Rucio)

From these, **Site Readiness** is computed → from which the four operational statuses are derived.

---

## 2. The four operational statuses

| Status | Purpose | Tier |
|--------|---------|------|
| **Life Status** | Is the site usable in the CMS grid? | T0, T1, T2 |
| **Prod Status** | Is the site enabled for production? | T0, T1, T2 |
| **Crab Status** | Can the site run user analysis jobs? | T0, T1, T2, T3 |
| **Rucio Status** | Is the site enabled for data transfers? | T0, T1, T2, T3 |

---

## 3. Life Status

### States
| Code | Symbol | Meaning |
|------|--------|---------|
| `ok` | (O) | Site in service |
| `waiting_room` | (WR) | Site temporarily out of service |
| `morgue` | (M) | Site out of service for an extended period |
| `unknown` | — | Status not determined |

### Evaluation
- **Frequency:** daily, early morning, after Site Readiness
- **Scope:** T0, T1, T2

### State machine

```
ok (or unknown)
  → waiting_room:  5th SR error state within 2 weeks

waiting_room (or unknown)
  → ok:            3 consecutive SR ok states
  → morgue:        45 days in waiting_room

morgue
  → waiting_room:  5th consecutive SR ok state
                   (~1 week of recommendation with manual Life Status override on WR)
                   (after that, override removed → can return to ok with 3-ok-in-a-row rule)
```

### Weekend rule (T2 and T3)
- **Error states on weekends: NOT counted**
- **Ok states on weekends: COUNTED**
- Rationale: T2/T3 sites operate 8x5; weekend errors will not be fixed until Monday, but weekend ok states allow rapid recovery.

---

## 4. Prod Status

### States
| Code | Meaning |
|------|---------|
| `enabled` | Site enabled for production |
| `drain` | New production workflows exclude the site |
| `disabled` | Site disabled for production jobs |
| `test` | Site under testing for production |
| `unknown` | Status not determined |

### Evaluation
- **Frequency:** daily, early morning, after Life Status
- **Scope:** T0, T1, T2
- **Window:** Site Readiness of the last **10 days**
- **Manual override:** production team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/ProdStatus

### State machine

```
[Automatic rules from Life Status]
Life Status = waiting_room (no override) → drain
Life Status = morgue (no override)       → disabled

[Downtime rule]
Scheduled or unscheduled downtime > 24h in the next 48h → drain

[SR rules]
enabled (or unknown)
  → drain:     2nd SR error state within 3 days

drain / disabled (or unknown)
  → enabled:   2 consecutive SR ok states
```

### Weekend rule (T2 and T3)
- Weekend error states: NOT counted
- Weekend ok states: COUNTED

---

## 5. Crab Status

### States
| Code | Meaning |
|------|---------|
| `enabled` | Site enabled for analysis jobs |
| `disabled` | Site disabled for analysis jobs |
| `unknown` | Status not determined |

### Evaluation
- **Frequency:** daily, early morning, after Life Status
- **Scope:** T0, T1, T2, T3 (only sites with active HC)
- **Window:** HammerCloud of the last **7 days** (for evaluation) / **3 days** (for rules)
- **Manual override:** CRAB-3 team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/CrabStatus

### State machine

```
[Automatic rules from Life Status]
Life Status = waiting_room or morgue (no override) → disabled

[HC rules]
→ disabled:  no HC ok state in the last 3 days
→ enabled:   1+ HC ok state in the last 3 days
```

**Note:** `Usable_Analysis` is a copy/derivative of Crab Status with legacy/historical codes.

---

## 6. Rucio Status

### States
| Code | Meaning |
|------|---------|
| `dependable` | Site fully enabled; storage considered robust (for data placement) |
| `enabled` | Site fully enabled for transfers |
| `new_data_stop` | No new data sent; reading/transfer from site still allowed |
| `downtime_stop` | Storage in downtime |
| `parked` | Site excluded from transfers |
| `disabled` | Site disabled, no unique data at the site |
| `unknown` | Status not determined |

### Evaluation
- **Frequency:** 4 times per day (~4 hours after each quarter-day)
- **Scope:** T0, T1, T2, T3 (only sites with storage)
- **Window:** SAM storage of the last **120 quarter-day = 30 days**
- **Manual override:** transfer team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/RucioStatus

### State machine

```
[Automatic rules from Life Status]
Life Status = waiting_room → parked
Life Status = morgue       → disabled

[Downtime rule]
Scheduled/unscheduled downtime > 24h in the next 6h → downtime_stop

[Degradation]
dependable/enabled
  → new_data_stop:  4th SAM storage error state within 3 days

new_data_stop
  → parked:         8th SAM storage error state within 3 days

any state
  → disabled:       ≥ 84 SAM storage error states in 30 days

[Recovery]
new_data_stop → enabled:   4 consecutive SAM storage ok states
parked        → enabled:   8 consecutive SAM storage ok states
disabled      → enabled:   12 consecutive SAM storage ok states

enabled → dependable:      ≥ 108 SAM storage ok in 30d AND error states < 24
dependable → enabled:      error states in 30d ≥ 24
```

### Weekend rule (T2 and T3)
- Weekend error states: NOT counted
- Weekend ok states: COUNTED (for rapid re-enable of working storage)

---

## 7. Site Readiness

### Evaluated periods
15 min, 1 hour, 6 hours, 1 day

### Metric: status + value
- **Status:** the most problematic state among SAM, HC, FTS
  Hierarchy: `error > unknown > warning > ok`
  Or: `downtime` if the site was in scheduled downtime for ≥ half the period
- **Value:** fraction of 15-min ok/warning states in the period
  (for 15min bin: 0 or 1)

### Scheduled downtime definition
At least one of: all CEs, all XRootD endpoints, or one storage element (SE) in scheduled downtime ≥ 24 hours in advance. Ok and warning states override downtime (shorter downtimes are handled automatically).

### Evaluation timing
| Granularity | When computed | Notes |
|-------------|--------------|-------|
| 15 min | 30 min after end of period | Updated/verified up to 3.5h after the bin |
| 1 hour | 3.5h after end | Final expected metric inputs |
| 6 hours | 3.5h after end | Final expected metric inputs |
| 1 day | 3.5h after end | Final expected metric inputs |

### Metric inputs
1. Downtime
2. SAM
3. HammerCloud
4. FTS

**Exclusions:** for sites without an active CE, HC is excluded. For sites without an active SE, FTS is excluded.

---

## 8. SAM — Technical details

**Profile used:** `CMS_CRITICAL_FULL`

**Tests per endpoint:**
- 5 tests per CE (Compute Element)
- 4 tests per XRootD endpoint
- 3 tests per SE/SRM

**Middleware:** gLite

### 15-min status logic per service
```
If no result in period → look at previous period (and half of previous)
If any test fails      → status = error
Else if results missing → status = unknown
Else if warning results → status = warning
Else (all ok)           → status = ok
```

### Site aggregation
```
Site status = most problematic of:
  - most problematic status of all SEs
  - LEAST problematic status among all CEs
  - least problematic status among all XRootD endpoints

If any SE is error         → site = error
If at least one CE is ok   → site = ok
```

### Availability/reliability calculation
```
availability = (ok + warning) / (ok + warning + critical + downtime)
reliability  = (ok + warning) / (ok + warning + critical)
(unknown excluded from numerator and denominator)
```

### Status thresholds (based on reliability)
| Reliability | T0/T1 | T2/T3 |
|-------------|-------|-------|
| > 90% | ok | ok |
| 80–90% | error | warning |
| < 80% | error | error |

**Downtime override:** if status = error or unknown AND site in scheduled downtime > half of the period → status = `downtime`

### Important notes
- **WLCG availability = SAM reliability** (profile `CMS_CRITICAL`, subset of CMS tests)
- The SAM calculation for Site Readiness is **independent of SAM3** and does NOT match it
- SAM result lifetime: ~30 min (vs ~1.5 days in the old system) → high priority for `lcgadmin` jobs

---

## 9. HammerCloud — Technical details

Analysis-type jobs launched via Glide-In WMS/CRAB.

**Test series characteristics:**
- Duration: ~2 days
- Frequency: ~1 job every 5 minutes per site
- Jobs not completed at end of series: cancelled

### Success formula
```
success = (AppSuccess - unsuccessful) / (Terminated - GridCancelled - unknown)

where:
  unsuccessful = AppSuccess & (GridAborted | GridCancelled)
  unknown      = AppUnknown & GridUnknown
```

### Status thresholds
| Success | T0/T1 | T2/T3 |
|---------|-------|-------|
| > 90% | ok | ok |
| 80–90% | error | warning |
| < 80% | error | error |
| No completed jobs | unknown | unknown |

---

## 10. FTS — Technical details

Evaluates links, transfer endpoints and data transfers based on CERN FTS logs (used by both PhEDEx and Rucio).

**Periods:** 15 min, 1 hour, 6 hours, 1 day

### Link status rules
```
≥ half transfers succeeded          → link = ok
> half transfers failed             → link = error
Few transfers with successes and failures → link = warning
No transfers                        → link = unknown
```

### Endpoint aggregation (from links)
```
> half links ok      → endpoint = ok
> half links error   → endpoint = error
Undetermined         → endpoint = warning
No transfers         → endpoint = unknown
```

### Site status
Most problematic state between source and destination endpoint of the site (according to VO-feed).

### Difference from PhEDEx (old system)
FTS only looks at file transfers; does not include PhEDEx service health check. If PhEDEx is down with zero transfers → FTS metric = `unknown` (instead of error).

---

## 11. Summary page architecture

### How it is generated

```
[Cron job] wrapper4cron.sh
    └── data_writer.py (timeout 1500s)
            ├── Reads metrics from HDFS/cache
            └── Writes summary.js → /data/cmssst/…/siteStatus/cache/

summary.html (static)
    ├── loads summary.js         (data, regenerated by cron)
    └── loads summary_lib.js     (HTML5 Canvas rendering)
```

The wrapper `wrapper4cron.sh`:
1. Acquires lock in `/var/tmp/cmssst/`
2. Validates Kerberos + AFS token
3. Runs `data_writer.py`
4. Alerts `lammel@cern.ch` if cache file > 24h

### Key files

| File | Purpose |
|------|---------|
| `siteStatus/summary.html` | Static HTML page |
| `siteStatus/summary_lib.js` | Canvas rendering + UI |
| `siteStatus/section_lib.js` | Site section rendering |
| `siteStatus/data_writer.py` | Generates summary.js |
| `siteStatus/wrapper4cron.sh` | Cron wrapper |

---

## 12. Repository structure

```
MonitoringScripts/
├── siteStatus/          # Dashboard writer + HTML/JS summary
├── sitereadiness/       # SR evaluator + HTML report
├── sam/                 # SAM ETF evaluator (eval_sam.py)
├── hammercloud/         # HC evaluator (eval_hc.py)
├── fts/                 # FTS evaluator (eval_fts.py)
├── downtime/            # OSG/EGI downtime evaluator
├── vofeed/              # VO topology (vofeed.py → XML + JSON)
├── cmssst/
│   ├── bin/             # correct.py (fix CLI), ssb_history.py
│   └── www/
│       ├── cgi-bin/     # man_override.py (web override CERN SSO)
│       ├── ranking/     # ranking index.html
│       └── site_info/   # site_endpoints.json
├── metrics/
│   ├── sam/             # sam.py, sam24.py
│   ├── hammercloud/     # hammercloud.py
│   ├── lifestatus/      # lifestatus.py
│   ├── prodstatus/      # productionStatus.py
│   ├── crabstatus/      # crabstatus.py
│   └── siteReadiness/   # dailyMetric.py
├── SR_View_SSB/         # Legacy SSB scripts (cron 15min)
│   ├── ActiveSites/     # T2 roster (Monday 08:00)
│   ├── WRControl/       # WaitingRoom_Sites.py (metric 153)
│   ├── drain/           # drain.py → drain.txt
│   └── morgue/          # morgue.py → morgue.txt
└── SiteComm/SSBScripts/ # EvaluateSiteReadinness.py (legacy)
```

---

## 13. Visualization — Data encoding in summary.js

### Time views per site (HTML5 Canvas)

| View | Granularity | Slots |
|------|-------------|-------|
| pmonth | 6h (last 30d) | 120 |
| pweek | 1h (last 7d) | 168 |
| yesterday | 15min | 96 |
| today | 15min | 96 |
| fweek | 1h (next 7d) | 168 |

### Character encoding in data strings

| Char | State | Color |
|------|-------|-------|
| `o` | ok | #80FF80 green |
| `w` | warning | yellow |
| `e` | error | red |
| `d` | full downtime | #6080FF blue |
| `p` | partial downtime | light blue |
| `a` | adhoc outage | orange |
| `r` | at-risk | — |
| `W` | waiting room | #A000A0 purple |
| `B` | morgue | #663300 brown |

Compound codes R/S/T/U/V/W/H/I/J/K/L/M encode combinations of states.

### GGUS tickets (highlighting)
| Condition | Color |
|-----------|-------|
| Ticket < 1h | dark orange |
| Ticket < 1d | light orange |
| Ticket older > 45d | brown |

### Responsive layout
| Width | Canvas bins |
|-------|-------------|
| < 1440px | reduced |
| 1440–2048px | standard |
| ≥ 4K | wide |

---

## 14. Manual Override System

### Web tool — `man_override.py`
- URL set LifeStatus: https://cmssst.web.cern.ch/cgi-bin/set/LifeStatus *(inferred)*
- URL set ProdStatus: https://cmssst.web.cern.ch/cgi-bin/set/ProdStatus
- URL set CrabStatus: https://cmssst.web.cern.ch/cgi-bin/set/CrabStatus
- URL set RucioStatus: https://cmssst.web.cern.ch/cgi-bin/set/RucioStatus
- Authentication: CERN SSO + e-group membership
- Allows setting: LifeStatus, ProdStatus, CrabStatus, RucioStatus, site capacity
- All changes are append-logged for audit
- File locking for concurrent writes

### CLI tool — `correct.py`
Fetch from HDFS → edit in `vi` → re-upload.
Supported metrics: `vofeed15min`, `down15min`, `sam`, `hc`, `fts`, `sr`, `sts`, `scap`

---

## 15. Key thresholds and parameters

| Parameter | Value |
|-----------|-------|
| **SAM ok** (T0/T1/T2) | reliability > 90% |
| **SAM warning** (T2) | reliability 80–90% |
| **SAM error** (T1) | reliability < 90% |
| **SAM error** (T2) | reliability < 80% |
| **HC ok** | success > 90% |
| **HC warning** (T2) | success 80–90% |
| **HC error** (T1) | success < 90% |
| **HC error** (T2) | success < 80% |
| **FTS ok** | ≥ half transfers succeeded |
| **FTS error** | > half transfers failed |
| **Downtime override** | ≥ 50% of period in scheduled downtime |
| **SR Life window** | 2 weeks |
| **Life ok→WR** | 5th SR error in 2 weeks |
| **Life WR→ok** | 3 consecutive SR ok states |
| **Life WR→morgue** | 45 days in WR |
| **Life morgue→WR** | 5th consecutive SR ok state |
| **Prod window** | 10 days SR |
| **Prod enabled→drain** | 2nd SR error in 3 days |
| **Prod drain→enabled** | 2 consecutive SR ok states |
| **Prod downtime drain** | downtime > 24h in next 48h |
| **Crab window** | 3 days HC |
| **Crab→disabled** | no HC ok in 3 days |
| **Crab→enabled** | 1+ HC ok in 3 days |
| **Rucio →new_data_stop** | 4th SAM storage error in 3 days |
| **Rucio →parked** | 8th SAM storage error in 3 days |
| **Rucio →disabled** | ≥ 84 SAM errors in 30 days |
| **Rucio →enabled** (from new_data_stop) | 4 consecutive SAM ok states |
| **Rucio →enabled** (from parked) | 8 consecutive SAM ok states |
| **Rucio →enabled** (from disabled) | 12 consecutive SAM ok states |
| **Rucio →dependable** | ≥ 108 SAM ok in 30d AND errors < 24 |
| **Rucio dependable→enabled** | errors in 30d ≥ 24 |
| **Rucio downtime_stop** | storage downtime > 24h in next 6h |
| **Cache expiry alert** | 24 hours |
| **data_writer.py timeout** | 1500 seconds |
| **SAM result lifetime** | ~30 min |

---

## 16. SSB → CERN MonIT migration differences

1. **FTS replaces PhEDEx:** FTS only looks at transfers; if PhEDEx is down with no transfers → FTS = `unknown`
2. **SAM uses reliability, not availability:** to avoid issues with downtimes not aligned to UTC days; error states during scheduled downtimes are excluded
3. **Site Readiness has a fractional value:** example: all tests ok but transfers only in the first 15 min of the day → SAM=HC=FTS=100% but SR value = 1/96 ≈ 1%; SR **status** remains `ok`
4. **SAM aggregation differs from SAM3:**
   - Ex. 1: CE error in the morning, SE error in the afternoon → SAM3=50%, new SAM=0%
   - Ex. 2: One of two CEs error in the morning, the other in the afternoon → SAM3=50%, new SAM=100%

---

## 17. Notes for future tool development

1. **Authoritative topology:** `vofeed.py` → use as source for any tool (CRIC + Rucio + HTCondor collectors)
2. **Kerberos required:** HDFS access requires a valid Kerberos ticket
3. **Override API:** the `/cgi-bin/set/` endpoints require CERN SSO; for automation consider direct HDFS use with locking
4. **correct.py:** CLI tool for point fixes on HDFS without the web UI
5. **summary.js format:** single-character encoding per bin (o/w/e/d/p/a/r/W/B + compounds) — study before building parser/writer
6. **Weekend rule:** any tool counting bad/good days for T2/T3 must ignore errors on weekends
7. **Rucio window:** 30 days / 120 quarter-day — much longer window than other statuses
8. **SAM result lifetime:** only ~30 min — SAM jobs (`lcgadmin`) must have high priority
9. **SR value vs status:** the SR value can be very low even with status ok — account for both

---

## 18. GGUS Tickets page — `ggus.html`

**URL:** https://cmssst.web.cern.ch/siteStatus/ggus.html

Shows the list of open GGUS tickets for each CMS site, grouped by age.

### Architecture (same as summary.html)

```
Cron (wrapper4cron.sh)
  └─> data_writer.py
        ├─ sswp_ggus()          → fetch tickets from GGUS REST API
        └─ sswp_write_ggus_js() → writes siteStatus/data/ggus.js

Browser loads ggus.html
  ├─ data/ggus.js      (siteStatusInfo + siteGGUSData)
  ├─ ggus_lib.js       (writeTable, fillLegend, updateTimestamps)
  └─ fillPage() → writeTable() → ticket table per site/age
```

### Step 1 — Fetch tickets: `sswp_ggus()` in `data_writer.py`

**GGUS API used (Zammad REST, current):**
```
GET https://helpdesk.ggus.eu/api/v1/groups
    → builds groupDict: {group_id → cms_site_name}

GET https://helpdesk.ggus.eu/api/v1/tickets/search
    Query: !((state:solved OR unsolved OR closed OR verified) AND id:>lastTicket)
    Params: sort_by=id, order_by=asc, limit=32
    Auth: Bearer token (redacted in repo)
```

Pagination: up to 64 batches × 32 tickets. Collects only **open/in-progress** tickets.

**Cache:** `cache/cache_ggus_grp.json` and `cache/cache_ggus.json` — used as fallback if live fetch fails.

**CMS site resolution per ticket** (priority order):
1. `ticket['cms_site_names']` — explicit Zammad field
2. `ticket['notified_groups']` → `groupDict[group_id]`
3. `ticket['wlcg_sites']` → `gridDict[wlcg_site]` (from VOFeed XML)

Tickets whose site does not match `T\d_[A-Z]{2}_\w+` are discarded.

### Step 2 — `ggus.js` format

```javascript
var siteStatusInfo = {
    time: 1774011242,   // Unix generation timestamp
    alert: "",
    reload: 900         // auto-reload in seconds
};

var siteGGUSData = [
    { site: "T0_CH_CERN",  ggus: [] },
    { site: "T1_IT_CNAF",  ggus: [[1000981, 1761577511]] },
    { site: "T1_RU_JINR",  ggus: [[1001605, 1768995854], [1001742, 1770239237]] },
    // ... ~116 sites
];
```

Each `ggus` element: `[ticket_id, unix_creation_timestamp]`, sorted by creation time ascending.

### Step 3 — Browser rendering: `ggus_lib.js`

`writeTable()` groups tickets by age relative to UTC midnight of the current day:

| Bucket | Condition |
|--------|-----------|
| Today | timestamp ≥ UTC midnight today |
| Yesterday | timestamp ≥ UTC midnight yesterday |
| Previous week | timestamp ≥ today − 7d |
| > 8 days | timestamp < today − 8d |

Each ticket is a link: `https://helpdesk.ggus.eu/#ticket/zoom/TICKET_ID`

### Files in the repository

| File | Role |
|------|------|
| `siteStatus/data_writer.py` | Master writer (5747 lines): `sswp_ggus()` + `sswp_write_ggus_js()` |
| `siteStatus/ggus.html` | Static HTML shell |
| `siteStatus/ggus_lib.js` | JS renderer (writeTable, fillLegend, updateTimestamps) |
| `siteStatus/wrapper4cron.sh` | Cron wrapper shared with summary.html |
| `GGUS_SOAP/ggus.py` | Legacy: SOAP client for ticket creation (suds library) |
| `GGUS_SOAP/metric.py` | Legacy: creates tickets for sites entering waiting_room |
| `metrics/ggus/ggus.py` | Legacy: XML parser → TWiki/SSB metric |
| `metrics/ggus/run.sh` | Legacy: wget with grid certificate → XML |
| `meeting_plots/meet_ggus.py` | Generates TWiki tables for CMS Ops meetings (on EOS) |
| `meeting_plots/ggus_wrapper4cron.sh` | Cron for meet_ggus.py |

### Notes for tool development

- Live data is in `data/ggus.js` — easy to parse (plain JS assignable as JSON)
- To create tickets automatically: `GGUS_SOAP/ggus.py` is the reference (now uses REST not SOAP)
- `meet_ggus.py` is useful as an example for generating tabular reports for meetings
- The Bearer token for the REST API is in `data_writer.py` (redacted in the public repo) — required for direct access

---

## 19. CMS SAM Tests — `gitlab.cern.ch/etf/cmssam`

> Repository: https://gitlab.cern.ch/etf/cmssam
> 1755 commits. Generates the ETF/Check_MK container that runs all SAM probes for CMS.

### What it is

A containerized appliance (ETF = European Testing Framework, based on Check_MK/Nagios) that:
1. At boot fetches X.509 proxy and OIDC token from `myproxy.cern.ch`
2. Generates the Nagios configuration for ~200 CMS sites by reading the VO feed
3. Continuously submits test jobs to all CMS sites via HTCondor-CE and ARC-CE
4. Collects results and publishes them to the WLCG STOMP broker (`oldsam.msg.cern.ch`, topic `/topic/sam.cms.metric`)

### Repository structure

```
cmssam/
├── Dockerfile                     # ETF container build (base: etf-base:el9)
├── .gitlab-ci.yml                 # CI: build→tag:qa, manual deploy→tag:prod
├── SiteTests/
│   ├── SE/                        # Storage Element probes (Python 3)
│   ├── WN/                        # Worker Node probes (Python 3 + shell)
│   ├── FroNtier/tests/            # Frontier/Squid CE probe (shell)
│   ├── MonteCarlo/                # MC stage-out probe (Python 2 + shell)
│   └── testjob/tests/             # CE job payload + libraries (shell + Python)
├── nagios/
│   ├── config/                    # Nagios/ETF config + etf_plugin_cms.py
│   └── org.cms.glexec/            # Legacy glexec probe (Perl + shell)
└── podman/
    ├── config/                    # ETF runtime config (ncgx, grid-env, OIDC)
    ├── add-keys.sh                # OIDC token init
    └── entrypoint.sh              # Full container startup
```

---

### Storage Element (SE) probes

| Probe | What it tests |
|-------|--------------|
| `se_xrootd.py` | 7 phases: TCP connect, version, stat/read/offset-read, foreign-file containment, open-access, write+checksum+delete, mkdir/ls/rmdir. Also validates IAM token auth. |
| `cmssam_xrootd_endpnt.py` | Lightweight XRootD endpoint: connect, version, read+Adler32 checksum on fixed blocks. Has `--generate` for data refresh from CMS global redirector. |
| `se_webdav.py` | ~18 steps: connectivity, SSL/TLS ciphers, certificate chain, X.509 CMS+non-CMS, OAuth2/IAM, macaroons, read/write/copy/delete, CRC32+Adler32. |
| `se_gsiftp.py` | TCP+SSL, GFAL2 read+checksum, write, VOMS attribute verification. IPv4/IPv6. |
| `se_links.py` | Third-party pull-copy: IAM token, copy test from T1/T2 EU/US/AS and T3 with Adler32 verification. |
| `srmvometrics.py` | Legacy SRM: put/get/ls/delete via gfal2, endpoint discovery via BDII/LDAP. |

### Worker Node (WN) probes

| Probe | What it tests |
|-------|--------------|
| `wn_basic.sh` | CPU, RAM (warn <2 GB/core), disk, load, NTP, IPv4/IPv6, Python3, OS (CentOS7 flag), X.509 or IAM token present. |
| `wn_cvmfs.sh` | Mount `cms.cern.ch`+`oasis.opensciencegrid.org`, CVMFS version, Stratum-1, proxy config, cache quota, I/O error counts. |
| `wn_apptainer.sh` | Finds Apptainer binary (env→CVMFS→which→modules), validates bind paths, runs payload inside container. |
| `wn_siteconf.py` | Validates `site-local-config.xml`, `storage.xml`, `storage.json` and compares with GitLab master (error if diverged > 120h). |
| `wn_dataaccess.py` | Creates CMSSW area, runs `cmsRun` on real ROOT GenericTTbar files. Supports PhEDEx XML and storage.json. |
| `wn_frontier.sh` | Launches `cmsRun` for `EcalPedestals` query via `frontier://FrontierProd`. Direct-server = error; proxy-failover = warning. |
| `wn_runsum.py` | Meta-orchestrator: runs multiple WN sub-probes inside Apptainer container (x86_64, ppc64le, aarch64), aggregates JSON output. |

### CE probes (job submission)

| Probe | What it tests |
|-------|--------------|
| `CE-cms-basic` | SITECONF (TFC, stage-out, frontier-connect, storage.json) vs GitLab master |
| `CE-cms-env` | Pilot environment: certificates, sw area, disk (min 10 GB), middleware, proxy (warn <6h) |
| `CE-cms-frontier` | Frontier/Squid connection via `cmsRun EcalPedestals` |
| `CE-cms-squid` | Squid connectivity |
| `CE-cms-xrootd-access` | Local XRootD read (T1=critical, T2=warning on error) |
| `CE-cms-xrootd-fallback` | XRootD read rotating across 10 global fallback sites |
| `CE-cms-analysis` | CMSSW analysis job on real data + FJR verification |
| `CE-cms-mc` | MC stage-out: TFC LFN→PFN + transfer + cleanup |
| `CE-cms-remotestageout` | Remote stage-out to CERN EOS, INFN Storm, UNL GridFTP |
| `CE-cms-singularity` | Singularity: CVMFS image present, runs `echo "Hello World"` |
| `CE-cms-isolation` | Proxy for combined glexec+Singularity test |

Each probe uses the SAME_* convention → Nagios exit code:

| SAME code | Exit | Nagios |
|-----------|------|--------|
| `SAME_OK = 10` | 0 | OK |
| `SAME_WARNING = 40` | 1 | WARNING |
| `SAME_ERROR = 50` | 2 | CRITICAL |
| timeout (exit 124) | 2 | CRITICAL |

The wrapper `nagtest-run` translates non-standard exit codes into correct Nagios output.

---

### SAM metric end-to-end flow

```
etf_plugin_cms.py
  └── reads VO feed from cmssst.web.cern.ch
  └── generates Nagios config for ~200 sites
        (placeholders: <siteName>, <ceName>, <VOMS>, ...)

wlcg_cms.cfg
  └── defines metrics (timeout=600s, retry=4, interval=30-60min)
  └── chain: proxy → job submit → job state → job monitor

Nagios/Check_MK (samtest-run)
  └── submits jobs via HTCondor-CE / ARC-CE
  └── payload = probe in /usr/libexec/grid-monitoring/probes/org.cms/

nstream (ocsp_handler.cfg)
  └── STOMP broker oldsam.msg.cern.ch
  └── topic /topic/sam.cms.metric
  └── → WLCG SAM dashboard → MonIT/HDFS → data_writer.py → summary.html
```

---

### Metric taxonomy (from `wlcg_cms.cfg`)

| Category | Metrics |
|----------|---------|
| Proxy | `org.cms.Proxy-lcgadmin`, `…-production`, `…-pilot` |
| OIDC | `org.cms.Token-CE`, `org.cms.Token-SR` |
| WN/CE jobs | `org.cms.WN-basic`, `…-cvmfs`, `…-frontier`, `…-squid`, `…-xrootd`, `…-xrootd-fallback`, `…-singularity`, `…-isolation`, `…-mc`, `…-analysis`, `…-remotestageout` |
| SE storage | `org.cms.SE-xrootd`, `…-xrootd-token`, `org.cms.SE-webdav-*`, `…-gsiftp-*`, `…-links` |
| CE submission | `org.cms.CE-jobsubmit`, `org.cms.CE-jobstate`, `emi.ce.CREAMCE-JobSubmit/State/Monit` |

---

### Container — Dockerfile

- **Base**: `gitlab-registry.cern.ch/etf/docker/etf-base:el9` (RHEL9)
- **Installed**: gfal2 stack (SRM, GridFTP, HTTP, XRootD), xrootd-client, Python 3 bindings
- **Probe paths**: `/usr/libexec/grid-monitoring/probes/org.cms/`
- **Config paths**: `/etc/ncgx/`, `/etc/nstream/`, `/etc/cron.d/`
- **Exposed ports**: 443 (Check_MK web UI), 6557 (Livestatus)
- **Entrypoint**: `/usr/sbin/init` (systemd)
- **CI**: `master` → tag `qa`; manual deploy → tag `prod` (via Crane)

---

### Notes for tool development

1. **`etf_plugin_cms.py`** is the Nagios config generator — study it to understand how the VO feed maps to sites/services/metrics
2. **`wlcg_cms.cfg`** contains all operational parameters (timeout, retry, interval) — authoritative source for timeout/retry values to replicate in custom tools
3. **SAME_* exit codes**: any custom tool/probe must use this convention to integrate with the system
4. **Singularity wrappers (`.sing`)**: reusable pattern for running probes in isolated containers
5. **`fetch-from-web-gitlab`**: contains a hardcoded GitLab PAT (redacted) — do not use as a model, it is an exposed credential in the public cmssam repo
6. **`ncgx.cfg`**: shows how metrics are published to STOMP — useful for understanding how to intercept/republish custom metrics

---

## 20. Daily Problem Report Tool — `cms_site_report.py`

> File: `cms_site_report.py` (in the Facilities directory)
> Generates a daily HTML report of CMS sites with problems.

### Features

- Downloads and parses `cmssst.web.cern.ch/sitereadiness/report.html` → SAM/HC/FTS per site
- Downloads open GGUS tickets via REST API (`helpdesk.ggus.eu/api/v1`) with description (first article)
- Shows only sites with **error** (severity >= 3), excluding `T2_RU_*` (being decommissioned)
- Order: Tier-1 → Tier-2 → Tier-3, within each tier: alphabetical
- Tickets sorted: **CMS VO** first, then **WLCG/general** — within each group: date descending
- Tickets > 90 days grouped in a collapsible `<details>` section with the same ordering

### Ticket classification: CMS vs WLCG

| GGUS field | Condition | Classification |
|-----------|-----------|---------------|
| `vo_support` | `== "cms"` | CMS (blue badge) |
| `area` | starts with `"CMS"` | CMS (blue badge) |
| everything else | — | WLCG (green badge) |

### Data sources

| Source | Access | Content |
|--------|--------|---------|
| `cmssst.web.cern.ch/sitereadiness/report.html` | Public | SAM%/HC%/FTS% per site, 16-day rolling, tooltip with details |
| `helpdesk.ggus.eu/api/v1/tickets/search` | Bearer token | Open tickets with cms_site_names, title, state, priority |
| `helpdesk.ggus.eu/api/v1/ticket_articles/{id}` | Bearer token | Body of first article (problem description) |

### GGUS Token

- File: `documentation/token_ggus`
- Header: `Authorization: Token <token>`
- The token is a personal Zammad API token created on `helpdesk.ggus.eu` → Settings → Token Access
- In the original system (`data_writer.py`) it is hardcoded in the source on the ETF instance

### Usage

```bash
# Standard report (error sites only, last 3 days)
python3 cms_site_report.py

# Wider window
python3 cms_site_report.py --days 7

# All sites (including ok and warning)
python3 cms_site_report.py --all

# Output to specific file
python3 cms_site_report.py --out /path/to/report.html
```

### Metric cell colors

| Color | Hex | Meaning |
|-------|-----|---------|
| Green | `#80FF80` | ok |
| Yellow | `#FFFF00` | warning |
| Red | `#FF0000` | error |
| Blue | `#6080FF` | scheduled downtime |
| Orange | `#FF8000` | adhoc/unscheduled |

### Configured exclusions

- `T2_RU_*` — being decommissioned (hardcoded in `show_all` filter)

---

## 21. Publishing on GitHub Pages

### Repository structure

```
.
├── cms_site_report.py          # main script
├── docs/
│   └── index.html              # generated report — served by GitHub Pages
├── .github/
│   └── workflows/
│       └── daily_report.yml    # GitHub Actions: daily update
├── run_report.command           # double-click from Finder → generate + open locally
└── .gitignore                  # excludes token and local output
```

### Initial setup (one time only)

#### 1. Create the repo on GitHub

```bash
cd /path/to/project
git init
git add cms_site_report.py docs/.gitkeep .github/ run_report.command .gitignore README_CMS_SST_Monitoring.md
git commit -m "initial commit"
gh repo create cms-sst-report --public --source=. --push
# or push to existing CERN repo
```

#### 2. Add token as GitHub Secret

```
GitHub → repo → Settings → Secrets and variables → Actions → New repository secret
  Name:  GGUS_TOKEN
  Value: (contents of documentation/token_ggus)
```

> **Warning:** the file `documentation/token_ggus` is in `.gitignore` — it is never committed.

#### 3. Enable GitHub Pages

```
GitHub → repo → Settings → Pages
  Source: Deploy from a branch
  Branch: main  /docs
```

The page will be available at:
`https://<username>.github.io/<repo>/`

#### 4. First manual run

```
GitHub → repo → Actions → Daily CMS SST Report → Run workflow
```

### How the GitHub Action works

The file `.github/workflows/daily_report.yml`:

1. Runs every day at **07:00 UTC** (after CERN overnight jobs complete)
2. Reads the token from the `GGUS_TOKEN` secret (env var `GGUS_TOKEN`)
3. Runs `python3 cms_site_report.py --days 3 --out docs/index.html`
4. Commits `docs/index.html` only if the content has changed
5. GitHub Pages automatically publishes the updated file

### Manual trigger

From the **Actions** menu on GitHub → select the workflow → **Run workflow**.

### Local update (run_report.command)

Double-click from Finder:
- generates `cms_report.html` in the project directory (not `docs/`)
- opens the file in the browser
- reads the token from `documentation/token_ggus`

---

## 22. References

| Resource | URL |
|----------|-----|
| Summary page | https://cmssst.web.cern.ch/siteStatus/summary.html |
| GGUS Tickets page | https://cmssst.web.cern.ch/siteStatus/ggus.html |
| GGUS helpdesk | https://helpdesk.ggus.eu/ |
| Site Readiness report | https://cmssst.web.cern.ch/sitereadiness/report.html |
| MonitoringScripts repo | https://github.com/CMSCompOps/MonitoringScripts |
| cmssam repo (SAM probes) | https://gitlab.cern.ch/etf/cmssam |
| TWiki SST (auth required) | https://twiki.cern.ch/twiki/bin/view/CMS/SiteSupportSiteStatusSiteReadiness |
| TWiki Facilities (public) | https://twiki.cern.ch/twiki/bin/view/CMSPublic/FacilitiesServicesDocumentation |
| TWiki SAM Tests | https://twiki.cern.ch/twiki/bin/view/CMSPublic/CompOpsSAMTests |
| TWiki WR/Morgue (legacy) | https://twiki.cern.ch/twiki/bin/view/CMSPublic/WaitingRoomMorgueAndSiteReadiness |
| Site Comm Rules | https://twiki.cern.ch/twiki/bin/viewauth/CMSPublic/SiteCommRules |
| SSB→MonIT migration talk | https://indico.cern.ch/event/870451/contributions/3671157/ |
| CRIC (site topology) | https://cms-cric.cern.ch/ |
| SAM ETF | https://wlcg-sam-cms.cern.ch/ |
| MonIT | https://monit.cern.ch/ |
| Published report | https://gbagliesi.github.io/cms-sst-report/ |

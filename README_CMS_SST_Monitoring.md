# CMS Site Support Team — Monitoring Infrastructure

> Knowledge base per lo sviluppo di tools legati alla pagina di monitoring
> https://cmssst.web.cern.ch/siteStatus/summary.html
>
> **Fonti:**
> - TWiki ufficiale: `CMS/SiteSupportSiteStatusSiteReadiness` (r27, 2024-10-02, S.Lammel)
> - Repo codice: https://github.com/CMSCompOps/MonitoringScripts

---

## 1. Overview

Il sistema monitora lo stato operativo di tutti i siti di computing CMS (Tier-0, Tier-1, Tier-2, Tier-3) nel WLCG.

**Tre input primari:**
1. **SAM Tests** — disponibilità servizi CE, SRM, WebDAV, XRootD
2. **HammerCloud Tests** — success rate job HTCondor/CRAB
3. **FTS Transfer Results** — qualità trasferimenti file (PhEDEx/Rucio sottostante)

Da questi viene calcolato **Site Readiness** → da cui derivano i quattro status operativi.

---

## 2. I quattro status operativi

| Status | Scopo | Tier |
|--------|-------|------|
| **Life Status** | Il sito è usabile nella grid CMS? | T0, T1, T2 |
| **Prod Status** | Il sito è abilitato per produzione? | T0, T1, T2 |
| **Crab Status** | Il sito può eseguire analisi utente? | T0, T1, T2, T3 |
| **Rucio Status** | Il sito è abilitato per trasferimenti dati? | T0, T1, T2, T3 |

---

## 3. Life Status

### Stati
| Codice | Simbolo | Significato |
|--------|---------|-------------|
| `ok` | (O) | Sito in servizio |
| `waiting_room` | (WR) | Sito temporaneamente fuori servizio |
| `morgue` | (M) | Sito fuori servizio per periodo esteso |
| `unknown` | — | Stato non determinato |

### Valutazione
- **Frequenza:** giornaliera, prima mattina, dopo Site Readiness
- **Scope:** T0, T1, T2

### Macchina a stati

```
ok (o unknown)
  → waiting_room:  5ª SR error state nell'arco di 2 settimane

waiting_room (o unknown)
  → ok:            3 SR ok states consecutivi
  → morgue:        45 giorni in waiting_room

morgue
  → waiting_room:  5ª SR ok state consecutiva
                   (poi ~1 settimana di raccomandazione con Life Status override manuale su WR)
                   (dopo, rimosso override → può tornare ok con regola 3-ok-in-a-row)
```

### Regola weekend (T2 e T3)
- **Error states nel weekend: NON contati**
- **Ok states nel weekend: CONTATI**
- Motivazione: i siti T2/T3 operano 8x5; gli errori del weekend non saranno corretti fino a lunedì, ma gli ok del weekend consentono rapido ripristino.

---

## 4. Prod Status

### Stati
| Codice | Significato |
|--------|-------------|
| `enabled` | Sito abilitato per produzione |
| `drain` | Nuovi workflow di produzione escludono il sito |
| `disabled` | Sito disabilitato per job di produzione |
| `test` | Sito in test per produzione |
| `unknown` | Stato non determinato |

### Valutazione
- **Frequenza:** giornaliera, prima mattina, dopo Life Status
- **Scope:** T0, T1, T2
- **Finestra:** Site Readiness degli ultimi **10 giorni**
- **Override manuale:** production team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/ProdStatus

### Macchina a stati

```
[Regole automatiche da Life Status]
Life Status = waiting_room (senza override) → drain
Life Status = morgue (senza override)       → disabled

[Regola downtime]
Downtime schedulato o non-schedulato > 24h nei prossimi 48h → drain

[Regole SR]
enabled (o unknown)
  → drain:     2ª SR error state nell'arco di 3 giorni

drain / disabled (o unknown)
  → enabled:   2 SR ok states consecutivi
```

### Regola weekend (T2 e T3)
- Error states weekend: NON contati
- Ok states weekend: CONTATI

---

## 5. Crab Status

### Stati
| Codice | Significato |
|--------|-------------|
| `enabled` | Sito abilitato per job di analisi |
| `disabled` | Sito disabilitato per job di analisi |
| `unknown` | Stato non determinato |

### Valutazione
- **Frequenza:** giornaliera, prima mattina, dopo Life Status
- **Scope:** T0, T1, T2, T3 (solo siti con HC attivo)
- **Finestra:** HammerCloud degli ultimi **7 giorni** (per la valutazione) / **3 giorni** (per le regole)
- **Override manuale:** CRAB-3 team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/CrabStatus

### Macchina a stati

```
[Regole automatiche da Life Status]
Life Status = waiting_room o morgue (senza override) → disabled

[Regole HC]
→ disabled:  nessun HC ok state negli ultimi 3 giorni
→ enabled:   1+ HC ok state negli ultimi 3 giorni
```

**Nota:** `Usable_Analysis` è una copia/derivazione di Crab Status con codici storici/legacy.

---

## 6. Rucio Status

### Stati
| Codice | Significato |
|--------|-------------|
| `dependable` | Sito completamente abilitato; storage considerato robusto (per data placement) |
| `enabled` | Sito completamente abilitato per trasferimenti |
| `new_data_stop` | Nessun dato nuovo inviato; lettura/trasferimento da sito ancora consentito |
| `downtime_stop` | Storage in downtime |
| `parked` | Sito escluso dai trasferimenti |
| `disabled` | Sito disabilitato, nessun dato unico nel sito |
| `unknown` | Stato non determinato |

### Valutazione
- **Frequenza:** 4 volte al giorno (~4 ore dopo ogni quarter-day)
- **Scope:** T0, T1, T2, T3 (solo siti con storage)
- **Finestra:** SAM storage degli ultimi **120 quarter-day = 30 giorni**
- **Override manuale:** transfer team, site admins, SST
- **Override URL:** https://cmssst.web.cern.ch/cgi-bin/set/RucioStatus

### Macchina a stati

```
[Regole automatiche da Life Status]
Life Status = waiting_room → parked
Life Status = morgue       → disabled

[Regola downtime]
Downtime schedulato/non-schedulato > 24h nelle prossime 6h → downtime_stop

[Degradazione]
dependable/enabled
  → new_data_stop:  4ª SAM storage error state nell'arco di 3 giorni

new_data_stop
  → parked:         8ª SAM storage error state nell'arco di 3 giorni

qualsiasi
  → disabled:       ≥ 84 SAM storage error states in 30 giorni

[Ripristino]
new_data_stop → enabled:   4 SAM storage ok consecutivi
parked        → enabled:   8 SAM storage ok consecutivi
disabled      → enabled:   12 SAM storage ok consecutivi

enabled → dependable:      ≥ 108 SAM storage ok in 30gg E error states < 24
dependable → enabled:      error states in 30gg ≥ 24
```

### Regola weekend (T2 e T3)
- Error states weekend: NON contati
- Ok states weekend: CONTATI (per rienable rapido di storage funzionante)

---

## 7. Site Readiness

### Periodi valutati
15 min, 1 ora, 6 ore, 1 giorno

### Metrica: status + value
- **Status:** lo stato più problematico tra SAM, HC, FTS
  Gerarchia: `error > unknown > warning > ok`
  Oppure: `downtime` se il sito era ≥ metà del periodo in downtime schedulato
- **Value:** frazione di 15-min ok/warning states nel periodo
  (per bin 15min: 0 o 1)

### Definizione downtime schedulato
Almeno uno di: tutti i CE, tutti i XRootD endpoint, oppure uno storage element (SE) in downtime schedulato ≥ 24 ore prima. Gli stati ok e warning sovrascrivono il downtime (downtime più brevi vengono gestiti automaticamente).

### Timing di valutazione
| Granularità | Quando viene fatto | Note |
|-------------|-------------------|------|
| 15 min | 30 min dopo la fine del periodo | Aggiornato/verificato fino a 3.5h dopo il bin |
| 1 ora | 3.5h dopo la fine | Input metriche attese finali |
| 6 ore | 3.5h dopo la fine | Input metriche attese finali |
| 1 giorno | 3.5h dopo la fine | Input metriche attese finali |

### Input metriche
1. Downtime
2. SAM
3. HammerCloud
4. FTS

**Esclusioni:** per siti senza CE attivo, HC è escluso. Per siti senza SE attivo, FTS è escluso.

---

## 8. SAM — Dettagli tecnici

**Profilo usato:** `CMS_CRITICAL_FULL`

**Test per endpoint:**
- 5 test per CE (Compute Element)
- 4 test per XRootD endpoint
- 3 test per SE/SRM

**Middleware:** gLite

### Logica stato 15-min per servizio
```
Se nessun risultato nel periodo → guarda periodo precedente (e metà del precedente)
Se qualsiasi test fallisce       → status = error
Else se risultati mancanti       → status = unknown
Else se risultati warning        → status = warning
Else (tutti ok)                  → status = ok
```

### Aggregazione sito
```
Status sito = più problematico tra:
  - status più problematico di tutti i SE
  - status MENO problematico tra tutti i CE
  - status meno problematico tra tutti i XRootD endpoint

Se qualsiasi SE è error         → sito = error
Se almeno un CE è ok            → sito = ok
```

### Calcolo availability/reliability
```
availability = (ok + warning) / (ok + warning + critical + downtime)
reliability  = (ok + warning) / (ok + warning + critical)
(unknown escluso da numeratore e denominatore)
```

### Soglie status (basate su reliability)
| Reliability | T0/T1 | T2/T3 |
|-------------|-------|-------|
| > 90% | ok | ok |
| 80–90% | error | warning |
| < 80% | error | error |

**Override downtime:** se status = error o unknown E sito in downtime schedulato > metà del periodo → status = `downtime`

### Note importanti
- **WLCG availability = SAM reliability** (profilo `CMS_CRITICAL`, subset dei test CMS)
- Il calcolo SAM per Site Readiness è **indipendente da SAM3** e NON coincide
- Lifetime risultati SAM: ~30 min (vs ~1.5 giorni nel vecchio sistema) → priorità alta ai job `lcgadmin`

---

## 9. HammerCloud — Dettagli tecnici

Jobs di tipo analisi lanciati tramite Glide-In WMS/CRAB.

**Caratteristiche serie di test:**
- Durata: ~2 giorni
- Frequenza: ~1 job ogni 5 minuti per sito
- Job non completati a fine serie: cancellati

### Formula successo
```
success = (AppSuccess - unsuccessful) / (Terminated - GridCancelled - unknown)

dove:
  unsuccessful = AppSuccess & (GridAborted | GridCancelled)
  unknown      = AppUnknown & GridUnknown
```

### Soglie status
| Success | T0/T1 | T2/T3 |
|---------|-------|-------|
| > 90% | ok | ok |
| 80–90% | error | warning |
| < 80% | error | error |
| Nessun job completato | unknown | unknown |

---

## 10. FTS — Dettagli tecnici

Valuta link, transfer endpoint e trasferimento dati basandosi sui log di CERN FTS (usato sia da PhEDEx che da Rucio).

**Periodi:** 15 min, 1 ora, 6 ore, 1 giorno

### Regole stato link
```
≥ metà trasferimenti riusciti        → link = ok
> metà trasferimenti falliti         → link = error
Pochi trasf. con successi e fallimenti → link = warning
Nessun trasferimento                  → link = unknown
```

### Aggregazione endpoint (da link)
```
> metà link ok      → endpoint = ok
> metà link error   → endpoint = error
Indeterminato       → endpoint = warning
Nessun trasf.       → endpoint = unknown
```

### Stato sito
Stato più problematico tra source e destination endpoint del sito (secondo VO-feed).

### Differenza rispetto a PhEDEx (vecchio sistema)
FTS guarda solo i trasferimenti file; non include health check del servizio PhEDEx. Se PhEDEx è down con zero trasferimenti → FTS metric = `unknown` (invece di error).

---

## 11. Architettura della summary page

### Come viene generata

```
[Cron job] wrapper4cron.sh
    └── data_writer.py (timeout 1500s)
            ├── Legge metriche da HDFS/cache
            └── Scrive summary.js → /data/cmssst/…/siteStatus/cache/

summary.html (statica)
    ├── carica summary.js         (dati, rigenerato da cron)
    └── carica summary_lib.js     (rendering HTML5 Canvas)
```

Il wrapper `wrapper4cron.sh`:
1. Acquisisce lock in `/var/tmp/cmssst/`
2. Valida token Kerberos + AFS
3. Esegue `data_writer.py`
4. Alert a `lammel@cern.ch` se cache file > 24h

### File chiave

| File | Scopo |
|------|-------|
| `siteStatus/summary.html` | Pagina HTML statica |
| `siteStatus/summary_lib.js` | Rendering Canvas + UI |
| `siteStatus/section_lib.js` | Rendering sezioni sito |
| `siteStatus/data_writer.py` | Genera summary.js |
| `siteStatus/wrapper4cron.sh` | Wrapper cron |

---

## 12. Struttura repository

```
MonitoringScripts/
├── siteStatus/          # Dashboard writer + HTML/JS summary
├── sitereadiness/       # Valutatore SR + report HTML
├── sam/                 # Valutatore SAM ETF (eval_sam.py)
├── hammercloud/         # Valutatore HC (eval_hc.py)
├── fts/                 # Valutatore FTS (eval_fts.py)
├── downtime/            # Valutatore downtime OSG/EGI
├── vofeed/              # Topologia VO (vofeed.py → XML + JSON)
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
├── SR_View_SSB/         # Script legacy SSB (cron 15min)
│   ├── ActiveSites/     # Roster T2 (lunedì 08:00)
│   ├── WRControl/       # WaitingRoom_Sites.py (metric 153)
│   ├── drain/           # drain.py → drain.txt
│   └── morgue/          # morgue.py → morgue.txt
└── SiteComm/SSBScripts/ # EvaluateSiteReadinness.py (legacy)
```

---

## 13. Visualizzazione — Encoding dati in summary.js

### Viste temporali per sito (HTML5 Canvas)

| Vista | Granularità | Slot |
|-------|-------------|------|
| pmonth | 6h (ultimi 30gg) | 120 |
| pweek | 1h (ultimi 7gg) | 168 |
| yesterday | 15min | 96 |
| today | 15min | 96 |
| fweek | 1h (prossimi 7gg) | 168 |

### Codifica caratteri negli string di dati

| Char | Stato | Colore |
|------|-------|--------|
| `o` | ok | #80FF80 verde |
| `w` | warning | giallo |
| `e` | error | rosso |
| `d` | full downtime | #6080FF blu |
| `p` | partial downtime | blu chiaro |
| `a` | adhoc outage | arancione |
| `r` | at-risk | — |
| `W` | waiting room | #A000A0 viola |
| `B` | morgue | #663300 marrone |

I codici composti R/S/T/U/V/W/H/I/J/K/L/M codificano combinazioni di stati.

### Ticket GGUS (highlighting)
| Condizione | Colore |
|------------|--------|
| Ticket < 1h | arancione scuro |
| Ticket < 1gg | arancione chiaro |
| Ticket più vecchio > 45gg | marrone |

### Layout responsive
| Larghezza | Bin Canvas |
|-----------|-----------|
| < 1440px | ridotta |
| 1440–2048px | standard |
| ≥ 4K | larga |

---

## 14. Manual Override System

### Web tool — `man_override.py`
- URL set LifeStatus: https://cmssst.web.cern.ch/cgi-bin/set/LifeStatus *(inferito)*
- URL set ProdStatus: https://cmssst.web.cern.ch/cgi-bin/set/ProdStatus
- URL set CrabStatus: https://cmssst.web.cern.ch/cgi-bin/set/CrabStatus
- URL set RucioStatus: https://cmssst.web.cern.ch/cgi-bin/set/RucioStatus
- Autenticazione: CERN SSO + e-group membership
- Permette impostare: LifeStatus, ProdStatus, CrabStatus, RucioStatus, capacità sito
- Tutte le modifiche sono append-logged per audit
- File locking per write concorrenti

### CLI tool — `correct.py`
Fetch da HDFS → modifica in `vi` → re-upload.
Metriche supportate: `vofeed15min`, `down15min`, `sam`, `hc`, `fts`, `sr`, `sts`, `scap`

---

## 15. Riepilogo soglie e parametri chiave

| Parametro | Valore |
|-----------|--------|
| **SAM ok** (T0/T1/T2) | reliability > 90% |
| **SAM warning** (T2) | reliability 80–90% |
| **SAM error** (T1) | reliability < 90% |
| **SAM error** (T2) | reliability < 80% |
| **HC ok** | success > 90% |
| **HC warning** (T2) | success 80–90% |
| **HC error** (T1) | success < 90% |
| **HC error** (T2) | success < 80% |
| **FTS ok** | ≥ metà trasferimenti riusciti |
| **FTS error** | > metà trasferimenti falliti |
| **Downtime override** | ≥ 50% del periodo in downtime schedulato |
| **SR finestra Life** | 2 settimane |
| **Life ok→WR** | 5ª SR error in 2 settimane |
| **Life WR→ok** | 3 SR ok consecutivi |
| **Life WR→morgue** | 45 giorni in WR |
| **Life morgue→WR** | 5ª SR ok consecutiva |
| **Prod finestra** | 10 giorni SR |
| **Prod enabled→drain** | 2ª SR error in 3 giorni |
| **Prod drain→enabled** | 2 SR ok consecutivi |
| **Prod downtime drain** | downtime > 24h nei prossimi 48h |
| **Crab finestra** | 3 giorni HC |
| **Crab→disabled** | nessun HC ok in 3 giorni |
| **Crab→enabled** | 1+ HC ok in 3 giorni |
| **Rucio →new_data_stop** | 4ª SAM storage error in 3 giorni |
| **Rucio →parked** | 8ª SAM storage error in 3 giorni |
| **Rucio →disabled** | ≥ 84 SAM error in 30 giorni |
| **Rucio →enabled** (da new_data_stop) | 4 SAM ok consecutivi |
| **Rucio →enabled** (da parked) | 8 SAM ok consecutivi |
| **Rucio →enabled** (da disabled) | 12 SAM ok consecutivi |
| **Rucio →dependable** | ≥ 108 SAM ok in 30gg E error < 24 |
| **Rucio dependable→enabled** | error in 30gg ≥ 24 |
| **Rucio downtime_stop** | storage downtime > 24h nelle prossime 6h |
| **Cache expiry alert** | 24 ore |
| **data_writer.py timeout** | 1500 secondi |
| **SAM result lifetime** | ~30 min |

---

## 16. Differenze SSB → CERN MonIT (migrazione)

1. **FTS sostituisce PhEDEx:** FTS guarda solo trasferimenti; se PhEDEx è down senza trasferimenti → FTS = `unknown`
2. **SAM usa reliability, non availability:** per evitare problemi con downtime non allineati a giorni UTC; stati error durante downtime schedulati sono esclusi
3. **Site Readiness ha un valore frazionario:** esempio: tutti i test ok ma i trasferimenti solo nei primi 15 min del giorno → SAM=HC=FTS=100% ma SR value = 1/96 ≈ 1%; SR **status** rimane `ok`
4. **Aggregazione SAM diversa da SAM3:**
   - Es. 1: CE error la mattina, SE error il pomeriggio → SAM3=50%, nuovo SAM=0%
   - Es. 2: Uno di due CE error la mattina, l'altro il pomeriggio → SAM3=50%, nuovo SAM=100%

---

## 17. Note per sviluppo futuro di tools

1. **Topologia autoritativa:** `vofeed.py` → usare come fonte per qualsiasi tool (CRIC + Rucio + HTCondor collectors)
2. **Kerberos richiesto:** accesso HDFS richiede ticket Kerberos valido
3. **Override API:** gli endpoint `/cgi-bin/set/` richiedono CERN SSO; per automazione valutare uso diretto HDFS con locking
4. **correct.py:** strumento CLI per patch puntuali su HDFS senza UI web
5. **Formato summary.js:** encoding a carattere singolo per bin (o/w/e/d/p/a/r/W/B + composti) — studiare prima di costruire parser/writer
6. **Weekend rule:** qualsiasi tool che conta bad/good days per T2/T3 deve ignorare error nel weekend
7. **Rucio finestra:** 30 giorni / 120 quarter-day — finestra molto più lunga degli altri status
8. **SAM result lifetime:** solo ~30 min — i job SAM (`lcgadmin`) devono avere alta priorità
9. **SR value vs status:** il valore SR può essere molto basso anche con status ok — tenere conto di entrambi

---

## 18. Pagina GGUS Tickets — `ggus.html`

**URL:** https://cmssst.web.cern.ch/siteStatus/ggus.html

Mostra l'elenco dei ticket GGUS aperti per ogni sito CMS, raggruppati per età.

### Architettura (stessa di summary.html)

```
Cron (wrapper4cron.sh)
  └─> data_writer.py
        ├─ sswp_ggus()          → fetch ticket da GGUS REST API
        └─ sswp_write_ggus_js() → scrive siteStatus/data/ggus.js

Browser carica ggus.html
  ├─ data/ggus.js      (siteStatusInfo + siteGGUSData)
  ├─ ggus_lib.js       (writeTable, fillLegend, updateTimestamps)
  └─ fillPage() → writeTable() → tabella ticket per sito/età
```

### Step 1 — Fetch ticket: `sswp_ggus()` in `data_writer.py`

**API GGUS usata (Zammad REST, attuale):**
```
GET https://helpdesk.ggus.eu/api/v1/groups
    → costruisce groupDict: {group_id → cms_site_name}

GET https://helpdesk.ggus.eu/api/v1/tickets/search
    Query: !((state:solved OR unsolved OR closed OR verified) AND id:>lastTicket)
    Params: sort_by=id, order_by=asc, limit=32
    Auth: Bearer token (in repo redatto)
```

Paginazione: fino a 64 batch × 32 ticket. Raccoglie solo ticket **open/in-progress**.

**Cache:** `cache/cache_ggus_grp.json` e `cache/cache_ggus.json` — usati come fallback se il fetch live fallisce.

**Risoluzione sito CMS per ticket** (ordine di priorità):
1. `ticket['cms_site_names']` — campo esplicito Zammad
2. `ticket['notified_groups']` → `groupDict[group_id]`
3. `ticket['wlcg_sites']` → `gridDict[wlcg_site]` (da VOFeed XML)

Ticket il cui sito non corrisponde a `T\d_[A-Z]{2}_\w+` vengono scartati.

### Step 2 — Formato `ggus.js`

```javascript
var siteStatusInfo = {
    time: 1774011242,   // Unix timestamp di generazione
    alert: "",
    reload: 900         // auto-reload in secondi
};

var siteGGUSData = [
    { site: "T0_CH_CERN",  ggus: [] },
    { site: "T1_IT_CNAF",  ggus: [[1000981, 1761577511]] },
    { site: "T1_RU_JINR",  ggus: [[1001605, 1768995854], [1001742, 1770239237]] },
    // ... ~116 siti
];
```

Ogni elemento `ggus`: `[ticket_id, unix_creation_timestamp]`, ordinato per creation time crescente.

### Step 3 — Rendering browser: `ggus_lib.js`

`writeTable()` raggruppa i ticket per età rispetto alla mezzanotte UTC del giorno corrente:

| Bucket | Condizione |
|--------|-----------|
| Oggi | timestamp ≥ mezzanotte UTC oggi |
| Ieri | timestamp ≥ mezzanotte UTC ieri |
| Settimana precedente | timestamp ≥ oggi − 7gg |
| > 8 giorni | timestamp < oggi − 8gg |

Ogni ticket è un link: `https://helpdesk.ggus.eu/#ticket/zoom/TICKET_ID`

### File coinvolti nel repo

| File | Ruolo |
|------|-------|
| `siteStatus/data_writer.py` | Master writer (5747 righe): `sswp_ggus()` + `sswp_write_ggus_js()` |
| `siteStatus/ggus.html` | Shell HTML statica |
| `siteStatus/ggus_lib.js` | Renderer JS (writeTable, fillLegend, updateTimestamps) |
| `siteStatus/wrapper4cron.sh` | Cron wrapper condiviso con summary.html |
| `GGUS_SOAP/ggus.py` | Legacy: SOAP client creazione ticket (suds library) |
| `GGUS_SOAP/metric.py` | Legacy: crea ticket per siti entrati in waiting_room |
| `metrics/ggus/ggus.py` | Legacy: parser XML → TWiki/SSB metric |
| `metrics/ggus/run.sh` | Legacy: wget con grid certificate → XML |
| `meeting_plots/meet_ggus.py` | Genera tabelle TWiki per meeting CMS Ops (su EOS) |
| `meeting_plots/ggus_wrapper4cron.sh` | Cron per meet_ggus.py |

### Note per sviluppo tools

- Il dato live è `data/ggus.js` — facile da parsare (plain JS assignable come JSON)
- Per creare ticket automaticamente: `GGUS_SOAP/ggus.py` è il modello (oggi usa REST non SOAP)
- `meet_ggus.py` è utile come esempio per generare report tabellari per meeting
- Il Bearer token per la REST API è in `data_writer.py` (redatto nel repo pubblico) — necessario per accesso diretto

---

## 19. CMS SAM Tests — `gitlab.cern.ch/etf/cmssam`

> Repository: https://gitlab.cern.ch/etf/cmssam
> 1755 commit. Genera il container ETF/Check_MK che esegue tutti i probe SAM per CMS.

### Cos'è

Un'appliance containerizzata (ETF = European Testing Framework, basato su Check_MK/Nagios) che:
1. Al boot fetcha proxy X.509 e token OIDC da `myproxy.cern.ch`
2. Genera la configurazione Nagios per ~200 siti CMS leggendo il VO feed
3. Sottopone continuamente job di test a tutti i siti CMS via HTCondor-CE e ARC-CE
4. Raccoglie i risultati e li pubblica sul broker STOMP WLCG (`oldsam.msg.cern.ch`, topic `/topic/sam.cms.metric`)

### Struttura del repository

```
cmssam/
├── Dockerfile                     # Build del container ETF (base: etf-base:el9)
├── .gitlab-ci.yml                 # CI: build→tag:qa, deploy manuale→tag:prod
├── SiteTests/
│   ├── SE/                        # Probe Storage Element (Python 3)
│   ├── WN/                        # Probe Worker Node (Python 3 + shell)
│   ├── FroNtier/tests/            # Probe Frontier/Squid CE (shell)
│   ├── MonteCarlo/                # Probe MC stage-out (Python 2 + shell)
│   └── testjob/tests/             # Job CE payload + librerie (shell + Python)
├── nagios/
│   ├── config/                    # Config Nagios/ETF + etf_plugin_cms.py
│   └── org.cms.glexec/            # Probe legacy glexec (Perl + shell)
└── podman/
    ├── config/                    # Config ETF runtime (ncgx, grid-env, OIDC)
    ├── add-keys.sh                # Init token OIDC
    └── entrypoint.sh              # Startup completo container
```

---

### Probe Storage Element (SE)

| Probe | Cosa testa |
|-------|-----------|
| `se_xrootd.py` | 7 fasi: TCP connect, versione, stat/read/offset-read, foreign-file containment, open-access, write+checksum+delete, mkdir/ls/rmdir. Valida anche IAM token auth. |
| `cmssam_xrootd_endpnt.py` | Endpoint XRootD leggero: connect, versione, read+checksum Adler32 su blocchi fissi. Ha `--generate` per refresh dati da redirector globale CMS. |
| `se_webdav.py` | ~18 passi: connettività, SSL/TLS ciphers, chain certificati, X.509 CMS+non-CMS, OAuth2/IAM, macaroons, read/write/copy/delete, CRC32+Adler32. |
| `se_gsiftp.py` | TCP+SSL, GFAL2 read+checksum, write, verifica attributi VOMS. IPv4/IPv6. |
| `se_links.py` | Third-party pull-copy: token IAM, copia test da T1/T2 EU/US/AS e T3 con verifica Adler32. |
| `srmvometrics.py` | Legacy SRM: put/get/ls/delete via gfal2, discovery endpoint BDII/LDAP. |

### Probe Worker Node (WN)

| Probe | Cosa testa |
|-------|-----------|
| `wn_basic.sh` | CPU, RAM (warn <2 GB/core), disk, load, NTP, IPv4/IPv6, Python3, OS (flag CentOS7), X.509 o IAM token presente. |
| `wn_cvmfs.sh` | Mount `cms.cern.ch`+`oasis.opensciencegrid.org`, versione CVMFS, Stratum-1, proxy config, cache quota, I/O error counts. |
| `wn_apptainer.sh` | Trova binario Apptainer (env→CVMFS→which→modules), valida bind paths, esegue payload dentro container. |
| `wn_siteconf.py` | Valida `site-local-config.xml`, `storage.xml`, `storage.json` e li confronta con GitLab master (error se diverge da >120h). |
| `wn_dataaccess.py` | Crea CMSSW area, esegue `cmsRun` su file ROOT GenericTTbar reali. Supporta PhEDEx XML e storage.json. |
| `wn_frontier.sh` | Lancia `cmsRun` per query `EcalPedestals` via `frontier://FrontierProd`. Direct-server = error; proxy-failover = warning. |
| `wn_runsum.py` | Meta-orchestratore: esegue più sub-probe WN dentro container Apptainer (x86_64, ppc64le, aarch64), aggrega output JSON. |

### Probe CE (job submission)

| Probe | Cosa testa |
|-------|-----------|
| `CE-cms-basic` | SITECONF (TFC, stage-out, frontier-connect, storage.json) vs GitLab master |
| `CE-cms-env` | Environment pilota: certificati, sw area, disco (min 10 GB), middleware, proxy (warn <6h) |
| `CE-cms-frontier` | Connessione Frontier/Squid via `cmsRun EcalPedestals` |
| `CE-cms-squid` | Connettività Squid |
| `CE-cms-xrootd-access` | Read XRootD locale (T1=critical, T2=warning su errore) |
| `CE-cms-xrootd-fallback` | Read XRootD ruotando su 10 siti fallback globali |
| `CE-cms-analysis` | Job analisi CMSSW su dati reali + verifica FJR |
| `CE-cms-mc` | Stage-out MC: TFC LFN→PFN + trasferimento + cleanup |
| `CE-cms-remotestageout` | Stage-out remoto verso CERN EOS, INFN Storm, UNL GridFTP |
| `CE-cms-singularity` | Singularity: immagine CVMFS presente, esegue `echo "Hello World"` |
| `CE-cms-isolation` | Proxy per test combined glexec+Singularity |

Ogni probe usa la convenzione SAME_* → exit code Nagios:

| SAME code | Exit | Nagios |
|-----------|------|--------|
| `SAME_OK = 10` | 0 | OK |
| `SAME_WARNING = 40` | 1 | WARNING |
| `SAME_ERROR = 50` | 2 | CRITICAL |
| timeout (exit 124) | 2 | CRITICAL |

Il wrapper `nagtest-run` traduce exit code non-standard in output Nagios corretto.

---

### Flusso metrica SAM end-to-end

```
etf_plugin_cms.py
  └── legge VO feed da cmssst.web.cern.ch
  └── genera config Nagios per ~200 siti
        (placeholder: <siteName>, <ceName>, <VOMS>, ...)

wlcg_cms.cfg
  └── definisce metriche (timeout=600s, retry=4, interval=30-60min)
  └── chain: proxy → job submit → job state → job monitor

Nagios/Check_MK (samtest-run)
  └── sottopone job via HTCondor-CE / ARC-CE
  └── payload = probe in /usr/libexec/grid-monitoring/probes/org.cms/

nstream (ocsp_handler.cfg)
  └── STOMP broker oldsam.msg.cern.ch
  └── topic /topic/sam.cms.metric
  └── → WLCG SAM dashboard → MonIT/HDFS → data_writer.py → summary.html
```

---

### Tassonomia metriche (da `wlcg_cms.cfg`)

| Categoria | Metriche |
|-----------|---------|
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
- **CI**: `master` → tag `qa`; deploy manuale → tag `prod` (via Crane)

---

### Note per sviluppo tools

1. **`etf_plugin_cms.py`** è il generatore di config Nagios — da studiare per capire come il VO feed si mappa su siti/servizi/metriche
2. **`wlcg_cms.cfg`** contiene tutti i parametri operativi (timeout, retry, interval) — fonte autorevole per timeout/retry da replicare in tool custom
3. **Exit code SAME_***: qualsiasi tool/probe custom deve usare questa convenzione per integrarsi con il sistema
4. **Singularity wrappers (`.sing`)**: pattern riutilizzabile per run di probe in container isolati
5. **`fetch-from-web-gitlab`**: contiene un GitLab PAT hardcoded (redacted) — non usarlo come modello, è una credenziale esposta nel repo pubblico cmssam
6. **`ncgx.cfg`**: mostra come le metriche vengono pubblicate su STOMP — utile per capire come intercettare/ripubblicare metriche custom

---

## 20. Daily Problem Report Tool — `cms_site_report.py`

> File: `cms_site_report.py` (nella directory Facilities)
> Genera un report HTML giornaliero dei siti CMS con problemi.

### Funzionalità

- Scarica e parsa `cmssst.web.cern.ch/sitereadiness/report.html` → SAM/HC/FTS per sito
- Scarica ticket GGUS aperti via REST API (`helpdesk.ggus.eu/api/v1`) con descrizione (primo articolo)
- Mostra solo siti con **errore** (severity >= 3), esclusi `T2_RU_*` (in dismissione)
- Ordine: Tier-2 → Tier-3 (nessun T1 in errore tipicamente), dentro ogni tier: alfabetico
- Ticket ordinati: **CMS VO** prima, poi **WLCG/generale** — dentro ogni gruppo: data decrescente
- Ticket >90 giorni raggruppati in sezione `<details>` espandibile con stesso ordinamento

### Classificazione ticket CMS vs WLCG

| Campo GGUS | Condizione | Classificazione |
|-----------|-----------|----------------|
| `vo_support` | `== "cms"` | CMS (badge blu) |
| `area` | inizia con `"CMS"` | CMS (badge blu) |
| tutto il resto | — | WLCG (badge verde) |

### Fonti dati

| Fonte | Accesso | Contenuto |
|-------|---------|-----------|
| `cmssst.web.cern.ch/sitereadiness/report.html` | Pubblico | SAM%/HC%/FTS% per sito, 16 giorni rolling, tooltip con dettagli |
| `helpdesk.ggus.eu/api/v1/tickets/search` | Bearer token | Ticket aperti con cms_site_names, titolo, stato, priorità |
| `helpdesk.ggus.eu/api/v1/ticket_articles/{id}` | Bearer token | Corpo del primo articolo (descrizione del problema) |

### Token GGUS

- File: `documentation/token_ggus`
- Header: `Authorization: Token <token>`
- Il token è un API token personale Zammad creato su `helpdesk.ggus.eu` → Settings → Token Access
- Nel sistema originale (`data_writer.py`) è hardcoded nel sorgente sull'istanza ETF

### Uso

```bash
# Report standard (soli siti in errore, ultimi 3 giorni)
python3 cms_site_report.py

# Finestra più ampia
python3 cms_site_report.py --days 7

# Tutti i siti (anche ok e warning)
python3 cms_site_report.py --all

# Output su file specifico
python3 cms_site_report.py --out /path/to/report.html
```

### Colori celle metriche

| Colore | Hex | Significato |
|--------|-----|-------------|
| Verde | `#80FF80` | ok |
| Giallo | `#FFFF00` | warning |
| Rosso | `#FF0000` | error |
| Blu | `#6080FF` | downtime schedulato |
| Arancione | `#FF8000` | adhoc/unscheduled |

### Esclusioni configurate

- `T2_RU_*` — in fase di dismissione (hardcoded nel filtro `show_all`)

---

## 21. Pubblicazione su GitHub Pages

### Struttura del repo

```
.
├── cms_site_report.py          # script principale
├── docs/
│   └── index.html              # report generato — servito da GitHub Pages
├── .github/
│   └── workflows/
│       └── daily_report.yml    # GitHub Actions: aggiornamento giornaliero
├── run_report.command           # doppio-click da Finder → genera + apre in locale
└── .gitignore                  # esclude il token e l'output locale
```

### Setup iniziale (una sola volta)

#### 1. Crea il repo su GitHub

```bash
cd /path/to/project
git init
git add cms_site_report.py docs/.gitkeep .github/ run_report.command .gitignore README_CMS_SST_Monitoring.md
git commit -m "initial commit"
gh repo create cms-sst-report --public --source=. --push
# oppure push su repo CERN esistente
```

#### 2. Aggiungi il token come GitHub Secret

```
GitHub → repo → Settings → Secrets and variables → Actions → New repository secret
  Nome:  GGUS_TOKEN
  Valore: (contenuto di documentation/token_ggus)
```

> **Attenzione:** il file `documentation/token_ggus` è in `.gitignore` — non viene mai committato.

#### 3. Abilita GitHub Pages

```
GitHub → repo → Settings → Pages
  Source: Deploy from a branch
  Branch: main  /docs
```

La pagina sarà disponibile a:
`https://<username>.github.io/<repo>/`

#### 4. Primo run manuale

```
GitHub → repo → Actions → Daily CMS SST Report → Run workflow
```

### Come funziona la GitHub Action

Il file `.github/workflows/daily_report.yml`:

1. Si esegue ogni giorno alle **07:00 UTC** (dopo i job notturni CERN)
2. Legge il token dal secret `GGUS_TOKEN` (env var `GGUS_TOKEN`)
3. Esegue `python3 cms_site_report.py --days 3 --out docs/index.html`
4. Committa `docs/index.html` solo se il contenuto è cambiato
5. GitHub Pages pubblica automaticamente il file aggiornato

### Trigger manuale

Dal menu **Actions** su GitHub → seleziona il workflow → **Run workflow**.

### Aggiornamento locale (run_report.command)

Doppio click da Finder:
- genera `cms_report.html` nella directory del progetto (non `docs/`)
- apre il file nel browser
- legge il token da `documentation/token_ggus`

---

## 22. Riferimenti

| Risorsa | URL |
|---------|-----|
| Summary page | https://cmssst.web.cern.ch/siteStatus/summary.html |
| GGUS Tickets page | https://cmssst.web.cern.ch/siteStatus/ggus.html |
| GGUS helpdesk | https://helpdesk.ggus.eu/ |
| Site Readiness report | https://cmssst.web.cern.ch/sitereadiness/report.html |
| Repo MonitoringScripts | https://github.com/CMSCompOps/MonitoringScripts |
| Repo cmssam (SAM probes) | https://gitlab.cern.ch/etf/cmssam |
| TWiki SST (auth) | https://twiki.cern.ch/twiki/bin/view/CMS/SiteSupportSiteStatusSiteReadiness |
| TWiki Facilities (pubblica) | https://twiki.cern.ch/twiki/bin/view/CMSPublic/FacilitiesServicesDocumentation |
| TWiki SAM Tests | https://twiki.cern.ch/twiki/bin/view/CMSPublic/CompOpsSAMTests |
| TWiki WR/Morgue (legacy) | https://twiki.cern.ch/twiki/bin/view/CMSPublic/WaitingRoomMorgueAndSiteReadiness |
| Site Comm Rules | https://twiki.cern.ch/twiki/bin/viewauth/CMSPublic/SiteCommRules |
| SSB→MonIT migration talk | https://indico.cern.ch/event/870451/contributions/3671157/ |
| CRIC (topologia siti) | https://cms-cric.cern.ch/ |
| SAM ETF | https://wlcg-sam-cms.cern.ch/ |
| MonIT | https://monit.cern.ch/ |

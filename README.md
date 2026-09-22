# facebook-adas-voice

Research-oriented customer-voice data pipeline that collects, cleans, filters, and
structures publicly/legitimately accessible Facebook community discussions about
ADAS (Advanced Driver Assistance Systems) user experience — focused on **PDA**
(Proactive Driving Assist) and **ACC** (Adaptive Cruise Control).

Target vehicles (configurable):

1. Jaecoo J5
2. Toyota Yaris
3. Toyota Zenix
4. Toyota Veloz
5. XPeng G6
6. BYD Sealion 7

The purpose is **customer-voice research**, not keyword counting. Every stage keeps
raw text intact, and every labelled result can be traced back to its source.

---

## 1. Project purpose

Collect community discussions (posts, comments, replies) about how users experience
PDA/ACC on the six target vehicles, then label them for:

- ADAS feature (PDA, ACC, both, unknown)
- Sub-feature (acceleration, braking, following distance, curve assist, ...)
- Driving scenario (tol/highway, traffic jam, stop-and-go, cut-in, ...)
- Evidence type (direct experience / opinion / question / hearsay / specification)
- Sentiment (positive / negative / neutral / mixed)
- User expectation mismatch (yes / no / unclear)
- Smoothness (smooth / slightly abrupt / abrupt / very abrupt / not stated)

The output supports a descriptive comparison across vehicles. It does **not** rank
vehicles, and comment counts are **not** treated as a measure of ADAS quality.

## 2. Architecture

```
Facebook community source        (legitimate, authorised access only)
        |
  Raw collection                 post -> comment -> reply hierarchy preserved
        |
  Deduplication                  community + post_id + comment_id (+ text hash fallback)
        |
  Cleaning                       whitespace/HTML/URL normalisation; RAW is never altered
        |
  Vehicle identification         configurable aliases per vehicle
        |
  Keyword candidate filtering    3 keyword layers (A feature names / B functional / C Indonesian)
        |
  Relevance screening            relevant / not_relevant / uncertain  (NOT driven by keywords alone)
        |
  PDA / ACC classification       feature + sub-feature from taxonomy config
        |
  Scenario / evidence / sentiment / expectation / smoothness classification
        |
  Customer Voice dataset + summary/export
```

## 3. Folder structure

```
facebook-adas-voice/
|-- config/                 YAML configuration (vehicles, keywords, taxonomy, communities, settings)
|-- data/
|   |-- raw/                raw records (CSV per run + append-only JSONL)
|   |-- clean/              cleaned records
|   |-- filtered/           relevant ADAS candidates
|   |-- labeled/            fully labelled experience records
|   `-- output/             final exports (CSV/JSON/XLSX) + summary + customer voice
|-- logs/                   structured run logs
|-- src/
|   |-- main.py             CLI entry point
|   |-- config_loader.py    central config + .env loader
|   |-- models.py           data schemas (Raw/Clean/Labeled)
|   |-- pipeline.py         orchestration
|   |-- storage/            SQLite checkpoint state + CSV/JSONL store
|   |-- collectors/         base / facebook / synthetic(mock)
|   |-- parsers/            raw dict -> RawRecord
|   |-- cleaners/           text cleaning (raw preserved)
|   |-- deduplication/      idempotent dedup
|   |-- filters/            keyword engine + relevance/evidence screening
|   |-- classifiers/        feature, scenario, sentiment, expectation, smoothness
|   `-- exporters/          exports, summary, customer voice, cross-vehicle snapshot
|-- tests/                  unit + e2e tests (no Facebook access required)
|-- scripts/run_stages.py   stage wrappers (raw/clean/filter/annotate/summary/export)
|-- .env.example            placeholder credentials (never commits real ones)
`-- README.md
```

## 4. Installation

Requirements: Python 3.10+.

```bash
cd facebook-adas-voice
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

Live Facebook scraping additionally needs a Chrome (or Chromium) browser and Selenium
drivers managed automatically by `webdriver-manager` (in requirements.txt).

## 5. Environment setup

Copy `.env.example` to `.env` and fill in only what you are legitimately authorized
to use:

- `FACEBOOK_COOKIES_FILE` — path to a cookies JSON exported from **your own**
  authorized, logged-in browser session.
- `FACEBOOK_USERNAME` / `FACEBOOK_PASSWORD` — reserve for an authorized local login
  flow only.
- `API_BASE_URL` / `API_TOKEN` — if you later integrate a legitimate API adapter.

`.env` is git-ignored. Project code never logs credentials.

## 6. Configuration

All configuration lives in `config/` (edit without touching Python):

- `vehicles.yaml` — canonical names, brand/model, aliases, per-vehicle feature terms,
  search keywords.
- `keywords.yaml` — three keyword layers (feature names, functional terms, Indonesian
  user language) plus generic ADAS terms.
- `taxonomy.yaml` — PDA/ACC sub-feature taxonomy with per-sub-feature keywords, and the
  driving-scenario taxonomy with keywords.
- `communities.yaml` — community entries per vehicle (URL, type, enabled, notes).
- `settings.yaml` — collection limits, pilot bounds, retry policy, paths, logging.

To add keywords, add/remove entries in `keywords.yaml` and bump `keyword_version` in
`settings.yaml`. Same for taxonomy. No code edits required.

## 7. Legitimate access requirements

- Only collect content your logged-in account is authorized to view.
- Do **not** bypass login walls, CAPTCHAs, access controls, or rate limits.
- Do **not** use stealth/evasion techniques. The Facebook collector uses a normal,
  human-paced browser session and *refuses* to proceed when the platform presents a
  login wall/checkpoint (it raises `AuthenticationError` and stops).
- Never use stolen/session credentials.
- Identities are anonymized in the analytical dataset (`USER_xxxx`).

**Authorized session setup (manual, required once):**

```bash
python -m src.main --mode login
```

This opens a **visible** Chrome window at facebook.com. You log in with your **own**
account manually (type the credentials and solve any CAPTCHA yourself — none of that
is automated or bypassed). When your home page is loaded, press Enter in the terminal.
The session is then:

1. persisted as a Chrome profile under `data/browser_profiles/facebook/` (reused
   automatically by later scrapes, including headless runs), and
2. dumped to `data/cookies_facebook.json` for the alternative cookie-injection path.

Accessible without a profile — a cookies JSON exported from your own authorized
browser session can be pointed to with `FACEBOOK_COOKIES_FILE` in `.env`.

If Facebook still blocks an automated session, the collector logs the failure, dumps a
screenshot and DOM snapshot under `logs/debug/`, and stops — while keeping all
previously collected data. The processing pipeline still works; swap in a legitimate
API/manual adapter via `data_source`.

## 8. Pilot execution

Pilot target is **Jaecoo J5**. The `mock` data source generates realistic synthetic
Jaecoo J5 threads so the entire pipeline can be validated without any Facebook access.

```bash
# Mock pilot (no Facebook needed) — 10-post bounded run:
python -m src.main --mode pilot --vehicle "Jaecoo J5" --data-source mock --max-posts 10

# Full pilot size (up to settings.pilot.max_posts = 50):
python -m src.main --mode pilot --vehicle "Jaecoo J5" --data-source mock
```

The pilot validates collection, comments, replies, raw storage, deduplication,
cleaning, keyword matching, relevance filtering, feature/scenario/evidence/sentiment
classification, expectation mismatch, smoothness, logging, checkpoint, and resume.

## 9. Full execution

1. Authenticate once (your own account, manual):

```bash
python -m src.main --mode login
```

2. Record community URLs in `config/communities.yaml` (set `enabled: true`).
3. Configure `data_source: facebook` (or keep `mock` for testing) in `settings.yaml`.
4. Run one vehicle at a time:

```bash
python -m src.main --mode scrape --vehicle "Toyota Yaris" --data-source facebook
```

The authenticated Chrome profile from step 1 is reused automatically (also allows
`--headed` if you want to watch it). Scale to the other five vehicles by editing
`communities.yaml` / setting `--vehicle`. The pipeline is identical for all six.

If you get `AuthenticationError`, re-run the login flow once (session expired),
make sure the profile directory is free (close other Chrome instances using it), or
point `FACEBOOK_COOKIES_FILE` at a fresh cookies export.

## 10. Resume execution

The pipeline persists processed posts/comments plus a dedup registry in
`data/scraper_state.db` (SQLite). Re-running the same command after an interruption
skips already-processed posts and continues.

```bash
python -m src.main --resume
```

Re-running any scrape is idempotent — it never duplicates records.

## 11. Output description

Final exports land in `data/output/`:

- `raw_data_final.{csv,xlsx,json}` — raw records (text untouched)
- `clean_data_final.*` — cleaned text (raw still preserved)
- `relevant_adas.*` — records screened as relevant ADAS customer-voice content
- `labeled_experience.*` — full annotation schema
- `customer_voice.*` — faithful per-aspect summaries (neutral wording; never fabricates)
- `summary.json` — counts: posts/comments/replies, unique records, candidates,
  relevant, PDA/ACC, distributions by vehicle/subfeature/scenario/evidence/sentiment,
  expectation-mismatch count, smoothness categories, top themes
- `cross_vehicle_descriptive.csv` — descriptive per-vehicle snapshot with caveats

## 12. Testing

Unit/integration tests do not require Facebook.

```bash
python -m pytest tests/ -q
```

Covered: keyword matching, vehicle identification, deduplication, cleaning, evidence
classification, sentiment, scenario, expectation mismatch, smoothness,
feature/sub-feature, schema validation, and an end-to-end mock pipeline run.

## 13. Troubleshooting

- `AuthenticationError: Facebook login wall / checkpoint detected` — your session is
  not authenticated or the platform checked your automated session. Re-run
  `python -m src.main --mode login` (you log in manually once) or replace
  `FACEBOOK_COOKIES_FILE` with a fresh cookies export from your own authorized
  session. A screenshot/DOM snapshot is saved under `logs/debug/`. No bypass is
  attempted by design.
- `py -m src.main` not found — use your venv interpreter: `.venv\Scripts\python.exe -m src.main ...`.
- Unicode/logging errors in terminals that are not UTF-8 — logs are written UTF-8 to
  `logs/`; terminals print with `errors=replace` so output never crashes.
- Selenium cannot start Chrome — install/update the matching ChromeDriver via
  `webdriver-manager` (bundled) or your package manager.
- Empty `relevant_adas` — check `keywords.yaml` coverage and `keyword_match_threshold`/
  `min_text_length` in `settings.yaml`.

## 14. Research limitations

- The resulting dataset represents **accessible community discussions**, **not** the
  entire population of vehicle users. Community size, activity level, data
  accessibility, terminology, and feature implementations differ per vehicle.
- Do not use raw comment counts as a proxy for ADAS quality. Cross-vehicle outputs are
  strictly descriptive.
- Keyword matches are candidate indicators only; relevance was screened heuristically
  and should be manually validated on a sample (`data/labeled/*.csv` — set
  `relevant = uncertain` status for review).
- By design, content behind login/access restrictions is not collected unless the
  account running the scraper is authorized to view it.

---

## 15. V2 reprocessing pipeline (data/output/by_vehicle_v2)

The **V2** pipeline re-processes all *existing* Facebook scrape artifacts without
scraping again and without modifying anything under `data/raw/`. It rebuilds one
most-complete master dataset and derives per-vehicle analysed outputs.

Key decisions (documented in `config/analysis.yaml`):

- **Master** = concatenation of all `data/raw/raw_data_run_*.csv` +
  `raw_data_all.jsonl` = **14 544** rows, deduplicated on `record_id`
  (fallback `community|post_id|comment_id`) = **4 556** unique records
  (identical to the old `raw_data_final.csv` count, but rebuilt from the raw layer).
- **`text_raw` is immutable**; `text_clean` (cleaning) and `text_normalized`
  (matching) are derived.
- **Vehicle identification is contextual**: explicit alias (high/medium) or
  community-scoped prior (medium). Conflicting/ambiguous rows land in
  `unknown_or_review.csv`.
- **ADAS relevance is layered** (`LayerScorer`): Layer A feature names (strong),
  Layer B functional, Layer C Indonesian (medium), `combined_adas` generic
  (uncertain). A keyword hit is only a candidate — relevance/confidence/reason
  are stored per record.
- Known noise is explicitly suppressed: `izin ACC mas admin` (marketplace admin
  approval), city acronym `BSD` (Bintaro Serpong Damai) vs Blind Spot Detection,
  and cosmetic phrases like *baret halus* / *PPF*.
- Feature label is restricted to `PDA | ACC | PDA+ACC | ADAS_OTHER | UNKNOWN`.

Run everything:

```bash
python scripts/run_pipeline.py                 # all stages (audit -> summary)
python scripts/run_pipeline.py --force         # force redo of every stage
python scripts/run_pipeline.py --stage clean   # single stage
python scripts/validate_pipeline.py            # 55-check final validation
streamlit run streamlit_app.py                 # interactive dashboard
```

Stages (`scripts/`): `audit_facebook_datasets`, `build_master_dataset`,
`deduplicate_facebook_data`, `clean_facebook_data`, `classify_vehicle`,
`filter_adas_relevance`, `classify_experience`, `split_by_vehicle`,
`generate_summary` (orchestrated by `run_pipeline.py`; shared helpers in
`v2_common.py`).

Output layout:

```
data/output/by_vehicle_v2/
|-- master/facebook_master_raw|deduplicated|clean|relevant.csv + processing_summary.json
|-- Jaecoo_J5/raw.csv|clean.csv|relevant.csv|analyzed.csv      (same for 5 other vehicles)
|-- combined/all_vehicles_clean|relevant|analyzed.csv
|-- unknown_or_review.csv        (conflicting / low-confidence vehicle identity)
|-- vehicle_summary.csv
```

### 15.1 Dashboard (Streamlit)

`streamlit_app.py` reads **only** real pipeline outputs (no hardcoded numbers):
pages Overview, Detail Kendaraan, PDA, ACC, Customer Voice, Data Quality; sidebar
filters (kendaraan, fitur, sentimen, jenis bukti, kata kunci); Plotly charts and
CSV/Excel downloads. It deliberately avoids any vehicle ranking and never treats
comment counts as a quality measure.

### 15.2 V2 caveats

- Content-identical comments in different posts/threads remain separate rows
  (dedup is based on post/comment identity, not text). `Data Quality` page shows
  the most repeated texts.
- Classification is heuristic/rule-based (plus taxonomy config). Manual spot-checks
  are recommended via `unknown_or_review.csv`, `relevant.csv`, and the
  `relevance_reason`/`evidence_type` columns.
- Numbers in this README (14 544 / 4 556 / 55) are snapshots of the current run;
  re-running `run_pipeline.py` after adding raw sources will update everything.
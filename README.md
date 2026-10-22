# Consumer financial health

A three-chart Streamlit dashboard for US consumer financial conditions, using FRED's public observation tables. No API key required.

| Chart | FRED series | Measurement |
| --- | --- | --- |
| Real disposable income growth | [DSPIC96](https://fred.stlouisfed.org/series/DSPIC96) | Monthly inflation-adjusted aggregate disposable income, transformed to percentage change versus the same month a year earlier |
| Personal saving rate | [PSAVERT](https://fred.stlouisfed.org/series/PSAVERT) | Monthly personal saving as a percentage of disposable income |
| Household debt service | [TDSP](https://fred.stlouisfed.org/series/TDSP) | Quarterly required mortgage and consumer debt payments as a percentage of disposable income |

## Run

Python 3.12 is used in this environment. From `/workspace/ChatGPT`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Use your hosting platform's supported application preview or deployment to view Streamlit. The cloud onboarding UI does not provide a localhost preview. To run on your own computer, clone the repository, run these commands from its directory, then open the local address printed by Streamlit.

## Network access

Outbound HTTPS access to **fred.stlouisfed.org** is required at runtime. Package installation uses **pypi.org** and **files.pythonhosted.org**. The cloud workspace and Streamlit Community Cloud have separate network settings; publishing the workspace configuration does not change Streamlit's access.

The app reads `https://fred.stlouisfed.org/data/<series>.txt`. Despite the `.txt` suffix, FRED currently serves an HTML page containing the full observation table and series metadata. The parser selects only that table, verifies the series ID and advertised date range, and validates dates and numeric values. The older `/graph/graph.csv` address returned HTTP 404 during investigation and is no longer used. No browser automation or additional parsing dependencies are needed.

Downloads run in parallel, retry once on temporary network errors, and use a 10-second per-request timeout on initial load. **Refresh data** allows 30 seconds per request and retries once; the three requests run together rather than adding their timeouts. TLS verification remains enabled. Results are cached in memory for one hour, including fallback outcomes so history filters do not trigger repeated failing downloads. Refresh clears that cache and fetches again.

Successful live downloads are also retained in the ignored `.cache/fred/` directory. If live FRED requests fail, the app uses the newest valid saved download from that cache or the real-data snapshots bundled in `data/`. Each affected chart displays a warning with its snapshot download date and the live error. The snapshots contain actual FRED observations with source URLs and timestamps, not sample data. They can become out of date and do not establish that the Streamlit server can reach FRED. If no valid snapshot exists, that panel shows an error. Monthly and quarterly releases do not share a common latest observation date.

To refresh the bundled snapshots from a machine that can reach FRED, run:

```bash
.venv/bin/python -m scripts.update_snapshots
```

Inspect and commit the updated `data/` files to deliver them to Streamlit. No scheduled refresh job is installed. Streamlit Community Cloud can lose its local cache after a reboot, but the committed snapshots remain available.

## Explore

Select 5, 10 or 20 years, or all history. Each chart includes hover values and an expandable definition, source link, displayed-data table and CSV download. The time window ends at the latest observation across available series. KPI changes use percentage points versus the same period a year earlier. Income growth is computed before filtering so history selection does not alter the calculation. Missing periods remain gaps.

These are national aggregates, not household-level financial assessments. FRED observations may be revised and source methodology may change; source links include the official notes. There is no fabricated overall health score or unsupported causal interpretation.

## Test

```bash
.venv/bin/python -m pytest -q
```

The lockfile includes the test runner. Tests use explicitly synthetic fixtures to check calendar alignment, missing observations, quarterly comparisons, all three charts, history filtering, partial failure and unavailable-source states. They do not establish live FRED connectivity. For a live check:

```bash
.venv/bin/python -c 'from fred_data import SERIES, fetch_series; [(print(s.id, fetch_series(s.id)[0].tail(1).to_string(index=False))) for s in SERIES]'
```

Use the existing checkout in this isolated cloud task; no Git worktree is needed.

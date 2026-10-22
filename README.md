# Consumer financial health

A three-chart Streamlit dashboard for US consumer financial conditions, using public FRED CSV downloads. No API key required.

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

Outbound HTTPS access to **fred.stlouisfed.org** is required at runtime. Package installation uses **pypi.org** and **files.pythonhosted.org**. The FRED network requirement has been saved in the cloud environment draft; review and save it in environment settings, then publish the environment to activate the configuration. Refresh the dashboard after access becomes available.

If FRED cannot be reached, each affected panel shows an error; the app never substitutes fabricated data. A successful download is cached in memory for one hour. **Refresh data** clears that cache and fetches again. No background refresh job is installed. Each panel shows its observation period and download timestamp; monthly and quarterly releases do not share a common latest date.

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

from unittest.mock import patch
from pathlib import Path
from io import BytesIO
from urllib.error import HTTPError
from urllib.error import URLError
import ssl

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import fred_data
from fred_data import FredError, chart_data, fetch_series, get_series, latest_summary, parse_csv, parse_table, period_label, read_snapshot, write_snapshot

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    # Synthetic tests must never write into the real cache or bundled snapshots.
    monkeypatch.setattr(fred_data, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(fred_data, "BUNDLE_DIR", tmp_path / "bundle")


def observation_page():
    # A minimal synthetic version of FRED's actual public table structure.
    return '''<html><table><tr><td>Unrelated navigation</td></tr></table>
    <table aria-label="metadata - Personal Saving Rate"><tbody>
    <tr><th>Series ID</th><td>PSAVERT</td></tr>
    <tr><th>Date Range</th><td>2024-01-01 to 2024-03-01</td></tr>
    </tbody></table>
    <table id="data-table-observations"><thead><tr><th>DATE</th><th>VALUE</th></tr></thead>
    <tbody><tr><th>2024-01-01</th><td> 4.2 </td></tr>
    <tr><th>2024-02-01</th><td>.</td></tr>
    <tr><th>2024-03-01</th><td>4.3</td></tr></tbody></table></html>'''


def test_official_table_and_transport():
    with patch("fred_data.urlopen", return_value=BytesIO(observation_page().encode())) as request:
        frame, fetched_at = fetch_series("PSAVERT")
    assert request.call_args.args[0].full_url == "https://fred.stlouisfed.org/data/PSAVERT.txt"
    assert len(frame) == 3
    assert frame.value.iloc[0] == 4.2
    assert pd.isna(frame.value.iloc[1])
    assert fetched_at.endswith("+00:00")


@pytest.mark.parametrize("text", [
    "<html>Access denied</html>",
    observation_page().replace("<td>PSAVERT</td>", "<td>TDSP</td>"),
    observation_page().replace("to 2024-03-01", "to 2024-04-01"),
    observation_page().replace("<td>4.3</td>", "<td>invalid</td>"),
    observation_page().replace("<th>VALUE</th>", "<th>CHANGED</th>"),
    observation_page().rsplit("</table>", 1)[0],
])
def test_table_rejects_wrong_series_incomplete_coverage_and_changed_format(text):
    with pytest.raises(FredError):
        parse_table(text, "PSAVERT")


def test_http_failure_reports_status():
    error = HTTPError("https://fred.stlouisfed.org/data/PSAVERT.txt", 403, "Forbidden", {}, None)
    with patch("fred_data.urlopen", side_effect=error):
        with pytest.raises(FredError, match="HTTP 403"):
            fetch_series("PSAVERT")


def test_missing_values_and_invalid_csv():
    frame = parse_csv("observation_date,PSAVERT\n2024-01-01,4.2\n2024-02-01,.\n", "PSAVERT")
    assert frame.value.iloc[0] == 4.2
    assert pd.isna(frame.value.iloc[1])
    for text in ("<html>Access denied</html>",
                 "DATE,PSAVERT\n2024-01-01,4\n2024-01-01,5",
                 "DATE,PSAVERT\n2024-01-01,not-a-number",
                 "DATE,PSAVERT\n2024-01-01,inf"):
        with pytest.raises(FredError):
            parse_csv(text, "PSAVERT")


def test_growth_uses_calendar_year_and_preserves_gaps():
    raw = pd.DataFrame({"date": pd.to_datetime(["2023-01-01", "2023-03-01", "2024-01-01", "2024-02-01"]),
                        "value": [100., 120., 110., 130.]})
    result = chart_data(raw, growth=True)
    assert result.loc[result.date.eq("2024-01-01"), "value"].iloc[0] == pytest.approx(10.)
    assert result.loc[result.date.eq("2024-02-01"), "value"].isna().all()
    assert result.loc[result.date.eq("2023-02-01"), "value"].isna().all()


def test_quarterly_comparison_is_year_over_year():
    raw = pd.DataFrame({"date": pd.to_datetime(["2023-04-01", "2024-01-01", "2024-04-01"]),
                        "value": [10., 11., 11.5]})
    date, value, change = latest_summary(raw)
    assert change == 1.5
    assert period_label(date, "Quarterly") == "Q2 2024"
    assert value == 11.5


def fixture_fetch(series_id, **kwargs):
    # Synthetic data used only in tests; never shipped as economic observations.
    dates = pd.date_range("2000-01-01", "2025-01-01", freq="QS" if series_id == "TDSP" else "MS")
    return pd.DataFrame({"date": dates, "value": [float(100 + i) for i in range(len(dates))]}), "2025-02-01T12:00:00+00:00"


def clear_cache():
    import streamlit as st
    st.cache_data.clear()


def test_dashboard_three_charts_and_history_filter():
    clear_cache()
    with patch("fred_data.fetch_series", side_effect=fixture_fetch):
        app = AppTest.from_file(APP).run(timeout=30)
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 3
        assert len(app.metric) == 3
        assert len(app.dataframe) == 3
        initial_rows = len(app.dataframe[0].value)
        app.button_group[0].set_value("5 years").run()
        assert not app.exception
        assert len(app.dataframe[0].value) < initial_rows
        assert len(app.get("vega_lite_chart")) == 3


def test_unavailable_source_has_no_fabricated_data():
    clear_cache()
    with patch("fred_data.fetch_series", side_effect=FredError("FRED network access blocked")):
        app = AppTest.from_file(APP).run(timeout=30)
        assert not app.exception
        assert len(app.error) == 3
        assert len(app.metric) == 0
        assert len(app.get("vega_lite_chart")) == 0
    clear_cache()


def test_partial_failure_keeps_other_charts():
    clear_cache()
    def partial(series_id, **kwargs):
        if series_id == "PSAVERT":
            raise FredError("Unavailable")
        return fixture_fetch(series_id)
    with patch("fred_data.fetch_series", side_effect=partial):
        app = AppTest.from_file(APP).run(timeout=30)
        assert not app.exception
        assert len(app.error) == 1
        assert len(app.get("vega_lite_chart")) == 2
    clear_cache()


def test_transient_timeout_is_retried():
    with patch("fred_data.urlopen", side_effect=[URLError(TimeoutError()), BytesIO(observation_page().encode())]) as request:
        with patch("fred_data.time.sleep"):
            frame, _ = fetch_series("PSAVERT", timeout=30)
    assert len(frame) == 3
    assert request.call_count == 2
    assert request.call_args.kwargs["timeout"] == 30


def test_tls_failure_is_not_retried():
    with patch("fred_data.urlopen", side_effect=URLError(ssl.SSLError("certificate failed"))) as request:
        with pytest.raises(FredError, match="could not be verified"):
            fetch_series("PSAVERT")
    assert request.call_count == 1


def test_snapshot_fallback_and_latest_success_survive_failure():
    frame, old_at = fixture_fetch("PSAVERT")
    write_snapshot("PSAVERT", frame, old_at, fred_data.BUNDLE_DIR)
    with patch("fred_data.fetch_series", side_effect=FredError("The request timed out.")):
        result, warning = get_series("PSAVERT")
    pd.testing.assert_frame_equal(frame, result[0])
    assert result[1] == old_at
    assert "Showing saved FRED data" in warning

    new_at = "2025-03-01T12:00:00+00:00"
    with patch("fred_data.fetch_series", return_value=(frame, new_at)):
        _, warning = get_series("PSAVERT")
    assert warning is None
    with patch("fred_data.fetch_series", side_effect=FredError("The request timed out.")):
        result, warning = get_series("PSAVERT")
    assert result[1] == new_at
    assert "01 Mar 2025" in warning


def test_invalid_snapshot_is_not_displayed():
    frame, at = fixture_fetch("PSAVERT")
    write_snapshot("PSAVERT", frame, at, fred_data.BUNDLE_DIR)
    path = fred_data.BUNDLE_DIR / "PSAVERT.json"
    path.write_text(path.read_text().replace('"series_id": "PSAVERT"', '"series_id": "TDSP"'))
    with patch("fred_data.fetch_series", side_effect=FredError("Unavailable")):
        result, warning = get_series("PSAVERT")
    assert result is None
    assert warning == "Unavailable"


def test_dashboard_renders_saved_data_when_all_live_requests_time_out():
    clear_cache()
    for series in fred_data.SERIES:
        write_snapshot(series.id, *fixture_fetch(series.id), fred_data.BUNDLE_DIR)
    with patch("fred_data.fetch_series", side_effect=FredError("The request timed out.")):
        app = AppTest.from_file(APP).run(timeout=30)
        assert not app.exception
        assert not app.error
        assert len(app.get("vega_lite_chart")) == 3
        assert len(app.warning) == 3
        assert all("Showing saved FRED data" in warning.value for warning in app.warning)
        app.button[0].click().run(timeout=30)
        assert len(app.get("vega_lite_chart")) == 3
    clear_cache()

from unittest.mock import patch
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from fred_data import FredError, chart_data, latest_summary, parse_csv, period_label

APP = str(Path(__file__).resolve().parents[1] / "app.py")


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


def fixture_fetch(series_id):
    # Synthetic data used only in tests; never shipped as economic observations.
    dates = pd.date_range("2000-01-01", "2025-01-01", freq="QS" if series_id == "TDSP" else "MS")
    return pd.DataFrame({"date": dates, "value": [100 + i for i in range(len(dates))]}), "2025-02-01T12:00:00+00:00"


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
    def partial(series_id):
        if series_id == "PSAVERT":
            raise FredError("Unavailable")
        return fixture_fetch(series_id)
    with patch("fred_data.fetch_series", side_effect=partial):
        app = AppTest.from_file(APP).run(timeout=30)
        assert not app.exception
        assert len(app.error) == 1
        assert len(app.get("vega_lite_chart")) == 2
    clear_cache()

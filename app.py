"""Run with: .venv/bin/streamlit run app.py"""

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from fred_data import SERIES, FredError, chart_data, data_url, fetch_series, latest_summary, period_label


st.set_page_config(page_title="Consumer financial health", page_icon="📊", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def load_series(series_id):
    return fetch_series(series_id)


def make_chart(frame, series):
    # Null separators prevent a line from silently bridging missing observations.
    plot = frame.copy()
    plot["segment"] = plot.value.isna().cumsum()
    plot["period"] = plot.date.map(lambda date: period_label(date, series.frequency))
    base = alt.Chart(plot).encode(
        x=alt.X("date:T", title=None,
                axis=alt.Axis(format="%Y", tickCount="year", labelOverlap=True, grid=False)),
        y=alt.Y("value:Q", title=series.unit, scale=alt.Scale(zero=True)),
        tooltip=[alt.Tooltip("period:N", title="Period"),
                 alt.Tooltip("value:Q", title=series.unit, format=".2f")],
    )
    line = base.mark_line(color=series.color, strokeWidth=2.5).encode(detail="segment:N")
    points = base.mark_point(color=series.color, filled=True, size=30, opacity=0.3)
    return (line + points).properties(height=280).configure_view(strokeWidth=0)


st.title("Consumer financial health")
st.caption("United States · Income, savings and household debt · Source: FRED")

controls, action = st.columns([4, 1], vertical_alignment="bottom")
with controls:
    window = st.segmented_control("History", ["5 years", "10 years", "20 years", "All history"], default="10 years")
with action:
    if st.button("Refresh data", width="stretch"):
        load_series.clear()

st.caption("Latest available observations are shown separately for each series; release dates differ. Refreshes are cached for one hour.")


def load_safely(series):
    try:
        return load_series(series.id), None
    except FredError as exc:
        return None, str(exc)


# Keep Streamlit's cache on the script thread; three bounded requests allow partial success.
results = [load_safely(series) for series in SERIES]
available = [result[0][0].date.max() for result in results if result[0] is not None]
end = max(available) if available else pd.Timestamp.today().normalize()
years = {"5 years": 5, "10 years": 10, "20 years": 20}.get(window)
start = end - pd.DateOffset(years=years) if years else None

if not available:
    st.warning("Unable to load FRED data. See the error details below, then select Refresh data to retry. No sample data is displayed.")

for series, (result, error) in zip(SERIES, results):
    with st.container(border=True):
        st.subheader(series.title)
        st.caption(f"{series.frequency} · {series.unit} · {series.id}")
        if error:
            st.error(error)
            st.link_button("View series on FRED", series.source_url)
            continue
        raw, fetched_at = result
        frame = chart_data(raw, growth=series.growth,
                           frequency="QS" if series.frequency == "Quarterly" else "MS")
        view = frame.loc[frame.date.ge(start)].copy() if start is not None else frame.copy()
        if view.value.notna().any():
            latest_visible = latest_summary(view)
            date, value, _ = latest_visible
            # Compare against full history, not the filtered view's first observation.
            annual = latest_summary(frame.loc[frame.date.le(date)])
            delta = annual[2]
            change_text = f"{delta:+.2f} pp vs a year earlier" if delta is not None else None
            st.metric(f"As of {period_label(date, series.frequency)}", f"{value:.2f}%", change_text, delta_color="off")
            st.altair_chart(make_chart(view, series), width="stretch")
        else:
            st.info("No observations are available in this history window.")
        with st.expander("Definition, source and data"):
            st.write(series.definition)
            st.markdown(f"[FRED series and release notes]({series.source_url}) · "
                        f"[Original observation table]({data_url(series.id)})")
            st.caption("FRED aggregates data from BEA (income and saving) and the Federal Reserve Board (debt service). "
                       "Observations can be revised; this app uses the latest available vintage. "
                       "Dates identify observation periods, not release dates. Missing values remain gaps.")
            st.caption(f"Fetched {datetime.fromisoformat(fetched_at).strftime('%d %b %Y, %H:%M UTC')}.")
            export = view.rename(columns={"value": series.unit})
            st.dataframe(export, hide_index=True, width="stretch")
            st.download_button("Download displayed data", export.to_csv(index=False),
                               file_name=f"{series.id}.csv", mime="text/csv", key=f"download-{series.id}")

st.caption("National aggregates can hide differences across households. These indicators describe economic conditions; they are not a personal credit score.")

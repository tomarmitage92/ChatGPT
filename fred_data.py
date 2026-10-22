"""Public FRED observation tables and calendar-aligned transformations."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd


@dataclass(frozen=True)
class Series:
    id: str
    title: str
    unit: str
    frequency: str
    definition: str
    color: str
    growth: bool = False

    @property
    def source_url(self) -> str:
        return f"https://fred.stlouisfed.org/series/{self.id}"


SERIES = (
    Series(
        "DSPIC96", "Real disposable income growth", "% year over year", "Monthly",
        "Inflation-adjusted disposable personal income for the United States, "
        "seasonally adjusted at an annual rate. Growth compares each month with "
        "the same month a year earlier: (income / income 12 months ago − 1) × 100. "
        "This is aggregate income, not income per person.",
        "#147D92", True,
    ),
    Series(
        "PSAVERT", "Personal saving rate", "% of disposable income", "Monthly",
        "Personal saving as a percentage of disposable personal income, seasonally "
        "adjusted. Measures the share of current income saved, not accumulated savings.",
        "#6752A2",
    ),
    Series(
        "TDSP", "Household debt service", "% of disposable income", "Quarterly",
        "Required household mortgage and consumer debt payments as a share of "
        "disposable personal income, seasonally adjusted. A higher rate means "
        "more income is committed to servicing debt.",
        "#C07830",
    ),
)


class FredError(ValueError):
    """A source could not be retrieved or validated."""


def data_url(series_id: str) -> str:
    return f"https://fred.stlouisfed.org/data/{series_id}.txt"


class _ObservationTableParser(HTMLParser):
    """Read only FRED's explicitly identified metadata and observation tables."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = {"metadata": [], "observations": []}
        self.kind = None
        self.depth = 0
        self.row = None
        self.cell = None
        self.closed = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self.kind:
                self.depth += 1
            elif attrs.get("id") == "data-table-observations":
                self.kind, self.depth = "observations", 1
            elif attrs.get("aria-label", "").startswith("metadata - "):
                self.kind, self.depth = "metadata", 1
        if self.kind and self.depth == 1:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.kind:
            return
        if self.depth == 1:
            if tag in ("td", "th") and self.cell is not None:
                self.row.append("".join(self.cell).strip())
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.tables[self.kind].append(self.row)
                self.row = None
        if tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.closed.add(self.kind)
                self.kind = None


def parse_table(text: str, series_id: str) -> pd.DataFrame:
    parser = _ObservationTableParser()
    parser.feed(text)
    parser.close()
    if parser.closed != {"metadata", "observations"}:
        raise FredError(f"FRED did not return complete data tables for {series_id}.")
    metadata = {row[0]: row[1] for row in parser.tables["metadata"] if len(row) == 2}
    rows = parser.tables["observations"]
    if metadata.get("Series ID") != series_id:
        raise FredError(f"FRED returned a different series than {series_id}.")
    if not rows or rows[0] != ["DATE", "VALUE"] or any(len(row) != 2 for row in rows):
        raise FredError(f"FRED's observation table format changed for {series_id}.")
    # Reuse the same strict numeric, missing-value and date checks as CSV ingestion.
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["DATE", series_id])
    writer.writerows(rows[1:])
    frame = parse_csv(buffer.getvalue(), series_id)
    coverage = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", metadata.get("Date Range", ""))
    if (not coverage or frame.date.min() != pd.Timestamp(coverage[1])
            or frame.date.max() != pd.Timestamp(coverage[2])):
        raise FredError(f"FRED's observations do not match its advertised date range for {series_id}.")
    return frame


def parse_csv(text: str, series_id: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False)
        date_column = next((c for c in ("observation_date", "DATE") if c in frame), None)
        if date_column is None or series_id not in frame:
            raise ValueError("Expected a FRED observation date and series column.")
        raw = frame[series_id].str.strip()
        values = pd.to_numeric(raw.mask(raw.isin([".", ""])), errors="raise")
        dates = pd.to_datetime(frame[date_column], errors="raise")
        if dates.isna().any() or dates.duplicated().any():
            raise ValueError("Observation dates must be present and unique.")
        result = pd.DataFrame({"date": dates, "value": values}).sort_values("date")
        if result.empty or not result.value.notna().any():
            raise ValueError("The source contains no usable observations.")
        if result.value.dropna().isin([float("inf"), float("-inf")]).any():
            raise ValueError("The source contains non-finite observations.")
        return result.reset_index(drop=True)
    except (ValueError, KeyError, pd.errors.ParserError) as exc:
        raise FredError(f"Invalid FRED CSV for {series_id}: {exc}") from exc


def fetch_series(series_id: str) -> tuple[pd.DataFrame, str]:
    if series_id not in {series.id for series in SERIES}:
        raise FredError("Unknown series.")
    url = data_url(series_id)
    request = Request(url, headers={"User-Agent": "ConsumerHealthDashboard/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise FredError(
            f"FRED returned HTTP {exc.code} for {series_id}. "
            "Try Refresh data. If it persists, check this app's access to fred.stlouisfed.org."
        ) from exc
    except (URLError, TimeoutError, UnicodeError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError,)):
            detail = "The request timed out."
        elif isinstance(reason, ssl.SSLError):
            detail = "The secure connection could not be verified."
        elif isinstance(reason, UnicodeError):
            detail = "The response could not be decoded."
        else:
            detail = "A connection to fred.stlouisfed.org could not be established."
        raise FredError(f"Could not load {series_id} from FRED. {detail} Try Refresh data.") from exc
    return parse_table(text, series_id), datetime.now(timezone.utc).isoformat()


def chart_data(raw: pd.DataFrame, growth: bool = False, frequency: str = "MS") -> pd.DataFrame:
    """Complete the source calendar so missing periods remain gaps, never zeros."""
    frame = raw.copy().set_index("date")
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq=frequency))
    if growth:
        prior = frame.value.shift(12)
        frame["value"] = (frame.value / prior.where(prior.ne(0)) - 1) * 100
    frame.index.name = "date"
    return frame.reset_index()


def latest_summary(frame: pd.DataFrame, months: int = 12):
    """Latest published observation and change versus the same period a year ago."""
    valid = frame.dropna(subset=["value"])
    if valid.empty:
        return None
    latest = valid.iloc[-1]
    previous_date = latest.date - pd.DateOffset(months=months)
    previous = frame.loc[frame.date.eq(previous_date), "value"].dropna()
    change = None if previous.empty else float(latest.value - previous.iloc[0])
    return latest.date, float(latest.value), change


def period_label(date: pd.Timestamp, frequency: str) -> str:
    return f"Q{date.quarter} {date.year}" if frequency == "Quarterly" else date.strftime("%b %Y")

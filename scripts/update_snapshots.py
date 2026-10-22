"""Refresh the real FRED data bundled with the app; run from the repository root."""

from concurrent.futures import ThreadPoolExecutor

from fred_data import BUNDLE_DIR, SERIES, fetch_series, write_snapshot


def main():
    # Download and validate every series before changing any bundled snapshot.
    with ThreadPoolExecutor(max_workers=3) as pool:
        downloads = list(pool.map(lambda series: fetch_series(series.id), SERIES))
    for series, (frame, fetched_at) in zip(SERIES, downloads):
        write_snapshot(series.id, frame, fetched_at, BUNDLE_DIR)
        print(f"{series.id}: {len(frame)} observations; latest period {frame.date.max().date()}; fetched {fetched_at}")


if __name__ == "__main__":
    main()

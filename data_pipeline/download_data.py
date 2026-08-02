"""Download 1-minute EUR/USD OHLC data from HistData.com for a range of years.

Source timestamps are HistData's "Eastern Standard Time, no DST" convention
(fixed UTC-5 all year round) -- see README.md in this directory.
"""
import argparse
import os
import zipfile

from histdata import download_hist_data as dl

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")


def download_year(pair: str, year: int, out_dir: str = RAW_DIR) -> str:
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"DAT_ASCII_{pair.upper()}_M1_{year}.csv")
    if os.path.exists(csv_path):
        print(f"[skip] {csv_path} already present")
        return csv_path

    zip_path = dl(year=str(year), pair=pair, time_frame="M1", platform="ASCII", output_directory=out_dir)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    os.remove(zip_path)
    print(f"[ok] {csv_path}")
    return csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="eurusd")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    for y in range(args.start_year, args.end_year + 1):
        download_year(args.pair, y)

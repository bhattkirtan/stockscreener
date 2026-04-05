#!/usr/bin/env python3
"""
subset_m1_data.py — Extract a date range from XAU_1m_data.csv and
normalise it to the project's standard OHLCV CSV format.

Usage:
    python3 subset_m1_data.py --from 2024-01-01 --to 2024-12-31
    python3 subset_m1_data.py --from 2023-01-01 --to 2025-12-31 --output GOLD_M1_3yr.csv
    python3 subset_m1_data.py --resample M5 --from 2024-01-01 --to 2024-12-31

Input:  cloud-function/data/archive (4)/XAU_1m_data.csv
Output: cloud-function/data/GOLD_M1_<from>_<to>.csv   (default)
        or --output path

Output columns (match project standard):
    timestamp, open, high, low, close, volume
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

SOURCE = Path(__file__).parent.parent / "cloud-function" / "data" / "archive (4)" / "XAU_1m_data.csv"
DATA_DIR = Path(__file__).parent.parent / "cloud-function" / "data"


def load_and_parse(source: Path) -> pd.DataFrame:
    print(f"📂 Loading {source} ({source.stat().st_size / 1e6:.0f} MB)...")
    df = pd.read_csv(
        source,
        sep=";",
        names=["timestamp", "open", "high", "low", "close", "volume"],
        header=0,
        dtype={"open": float, "high": float, "low": float, "close": float, "volume": float},
    )
    # Normalise timestamp: '2024.06.11 07:18' → '2024-06-11 07:18:00'
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M")
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"   Loaded {len(df):,} rows  |  {df['timestamp'].min()} → {df['timestamp'].max()}")
    return df


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    df2 = df.set_index("timestamp")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    resampled = df2.resample(rule, label="left", closed="left").agg(agg).dropna()
    return resampled.reset_index()


RESAMPLE_RULES = {
    "M1": None, "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h", "H4": "4h", "D1": "1D",
}


def main():
    parser = argparse.ArgumentParser(description="Subset XAU M1 data to a date range")
    parser.add_argument("--from", dest="from_date", required=True,
                        help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--to",   dest="to_date",   required=True,
                        help="End date   YYYY-MM-DD (inclusive)")
    parser.add_argument("--resample", default="M1", choices=RESAMPLE_RULES,
                        help="Resample to higher timeframe (default: M1 = no resample)")
    parser.add_argument("--output", default=None,
                        help="Output filename (default: auto-named in cloud-function/data/)")
    args = parser.parse_args()

    from_dt = pd.Timestamp(args.from_date)
    to_dt   = pd.Timestamp(args.to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    df = load_and_parse(SOURCE)

    # Filter
    mask = (df["timestamp"] >= from_dt) & (df["timestamp"] <= to_dt)
    df = df[mask].copy()
    print(f"   After filter:  {len(df):,} rows  |  {df['timestamp'].min()} → {df['timestamp'].max()}")

    if df.empty:
        print("❌ No data in that date range.")
        sys.exit(1)

    # Resample if requested
    if args.resample != "M1":
        rule = RESAMPLE_RULES[args.resample]
        df = resample_ohlcv(df, rule)
        print(f"   Resampled → {args.resample}: {len(df):,} bars")

    # Normalise timestamp column to string
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # Output path
    if args.output:
        out = DATA_DIR / args.output if not Path(args.output).is_absolute() else Path(args.output)
    else:
        tag = f"{args.from_date.replace('-','')}_{args.to_date.replace('-','')}"
        out = DATA_DIR / f"GOLD_{args.resample}_{tag}.csv"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    size_mb = out.stat().st_size / 1e6
    print(f"\n✅ Saved {len(df):,} rows → {out}  ({size_mb:.1f} MB)")
    print(f"   Columns: {list(df.columns)}")
    print(f"   Range:   {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")


if __name__ == "__main__":
    main()

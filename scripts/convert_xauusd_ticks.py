import argparse
from pathlib import Path
import pandas as pd

TIMEFRAMES = ["M1","M2","M3","M4","M5","M6","M10","M12","M15","M20","M30","H1","H2","H3","H4","H6","H8","H12","D1","W1","MN1"]


def tf_rule(tf: str) -> str:
    if tf.startswith("M") and tf != "MN1":
        return f"{int(tf[1:])}min"
    if tf.startswith("H"):
        return f"{int(tf[1:])}h"
    if tf == "D1":
        return "1D"
    if tf == "W1":
        return "W-SUN"
    if tf == "MN1":
        return "MS"
    raise ValueError(tf)


def to_export_format(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = out.index.strftime("%Y.%m.%d %H:%M")
    out["volume"] = out["volume"].astype(int)
    return out[["time", "open", "high", "low", "close", "volume", "spread"]]


def aggregate_ticks(chunk: pd.DataFrame) -> pd.DataFrame:
    g = chunk.groupby("minute", sort=True)
    return g.agg(
        open=("mid", "first"),
        high=("mid", "max"),
        low=("mid", "min"),
        close=("mid", "last"),
        volume=("mid", "size"),
        spread=("spread", "median"),
    )


def build_m1_from_zip(zip_path: Path, out_path: Path, chunksize: int = 1_000_000, append: bool = False) -> int:
    pending = pd.DataFrame(columns=["Timestamp", "mid", "spread", "minute"])
    wrote_rows = 0
    first_write = not append

    reader = pd.read_csv(
        zip_path,
        compression="zip",
        usecols=["Timestamp", "Bid", "Ask"],
        chunksize=chunksize,
        low_memory=False,
    )

    for chunk in reader:
        chunk["Timestamp"] = pd.to_datetime(chunk["Timestamp"], utc=True, errors="coerce")
        chunk = chunk.dropna(subset=["Timestamp", "Bid", "Ask"])
        if chunk.empty:
            continue

        chunk["Timestamp"] = chunk["Timestamp"].dt.tz_convert(None)
        chunk["mid"] = (chunk["Bid"] + chunk["Ask"]) / 2.0
        chunk["spread"] = (chunk["Ask"] - chunk["Bid"]).clip(lower=0)
        chunk["minute"] = chunk["Timestamp"].dt.floor("min")
        chunk = chunk[["Timestamp", "mid", "spread", "minute"]].sort_values("Timestamp")

        if not pending.empty:
            chunk = pd.concat([pending, chunk], ignore_index=True)
            chunk = chunk.sort_values("Timestamp")

        last_minute = chunk["minute"].iloc[-1]
        keep = chunk["minute"] == last_minute
        pending = chunk.loc[keep, ["Timestamp", "mid", "spread", "minute"]].copy()
        finalize = chunk.loc[~keep]

        if not finalize.empty:
            m1 = aggregate_ticks(finalize)
            export = to_export_format(m1)
            export.to_csv(out_path, mode="w" if first_write else "a", index=False, header=first_write)
            first_write = False
            wrote_rows += len(export)

    if not pending.empty:
        m1 = aggregate_ticks(pending)
        export = to_export_format(m1)
        export.to_csv(out_path, mode="w" if first_write else "a", index=False, header=first_write)
        wrote_rows += len(export)

    return wrote_rows


def resample_from_m1(m1_df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "M1":
        return m1_df
    rule = tf_rule(tf)
    out = m1_df.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        spread=("spread", "median"),
    )
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip-dir", default="data/raw/XAUUSD")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--chunksize", type=int, default=1_000_000)
    args = ap.parse_args()

    zip_dir = Path(args.zip_dir)
    zips = sorted(zip_dir.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No zip files found in {zip_dir}")

    out_root = Path("data/raw")
    out_root.mkdir(parents=True, exist_ok=True)
    m1_file = out_root / f"{args.symbol}_M1.csv"
    if m1_file.exists():
        m1_file.unlink()

    total_rows = 0
    for i, z in enumerate(zips, start=1):
        rows = build_m1_from_zip(z, m1_file, chunksize=args.chunksize, append=(i > 1))
        total_rows += rows
        print(f"[{i}/{len(zips)}] {z.name} -> M1 rows written: {rows}")

    m1 = pd.read_csv(m1_file)
    m1["ts"] = pd.to_datetime(m1["time"], format="%Y.%m.%d %H:%M", errors="coerce")
    m1 = m1.dropna(subset=["ts"]).drop_duplicates(subset=["ts"]).sort_values("ts")
    for c in ["open", "high", "low", "close", "volume", "spread"]:
        m1[c] = pd.to_numeric(m1[c], errors="coerce")
    m1 = m1.dropna(subset=["open", "high", "low", "close"])
    m1 = m1.set_index("ts")[["open", "high", "low", "close", "volume", "spread"]]
    to_export_format(m1).to_csv(m1_file, index=False)

    for tf in TIMEFRAMES:
        out_file = out_root / f"{args.symbol}_{tf}.csv"
        bars = resample_from_m1(m1, tf)
        to_export_format(bars).to_csv(out_file, index=False)
        print(f"saved {out_file} rows={len(bars)}")

    print(f"Done. Source zip={len(zips)}; total M1 chunk rows={total_rows}")


if __name__ == "__main__":
    main()

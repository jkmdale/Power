#!/usr/bin/env python3
"""Import whole-house usage from a Genesis Energy CSV export.

No hardware required — loads data you already have so the "Whole House" dashboard
can chart trends and cost. Auto-detects the export shape:

  * DAILY  — Genesis "My Daily Usage": columns date, usage ("34.64 kWh"),
             dollars ("$10.99"), type ("actual"/"powerShout"). -> meter_daily_usage
  * HOURLY — an interval export with a datetime + kWh column.   -> meter_hourly

Values like "34.64 kWh" and "$10.99" are cleaned automatically. Genesis dates are
NZ local; daily rows are stored as a plain DATE (no timezone ambiguity), hourly
rows are converted to UTC.

Usage:
    python tools/import_genesis.py path/to/export.csv
    DATABASE_URL=postgresql://energy:energy@localhost:5432/energy \
        python tools/import_genesis.py export.csv --source genesis
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncpg

NZ = ZoneInfo("Pacific/Auckland")
UTC = ZoneInfo("UTC")

_KWH_HINTS = ("usage", "kwh", "consumption", "energy")
_DOLLAR_HINTS = ("dollar", "cost", "amount", "charge", "$")
_TYPE_HINTS = ("type", "status")
_TS_HINTS = ("datetime", "timestamp", "date/time", "read", "interval", "period", "start")
_DATE_HINTS = ("date", "day")
_DT_FORMATS = (
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%d-%m-%Y %H:%M", "%d-%m-%Y",
)


def _num(value: str) -> float | None:
    """Strip units/symbols ($, kWh, commas, quotes) and return a float."""
    s = re.sub(r"[^0-9.\-]", "", (value or "").strip())
    if s in ("", "-", ".", "--"):
        return None
    return float(s)


def _parse_dt(value: str) -> datetime:
    v = value.strip().strip('"')
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        pass
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date/time: {value!r}")


def _find(cols: list[str], hints: tuple[str, ...]) -> str | None:
    for c in cols:
        cl = c.lower()
        if any(h in cl for h in hints):
            return c
    return None


def parse_csv(path: str):
    """Return ('daily', [(date, kwh, dollars, type)]) or ('hourly', [(ts_utc, kwh)])."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header row")
        cols = [c for c in reader.fieldnames if c]
        rows = list(reader)

    kwh_col = _find(cols, _KWH_HINTS)
    ts_col = _find(cols, _TS_HINTS)
    date_col = _find(cols, _DATE_HINTS)
    dollar_col = _find(cols, _DOLLAR_HINTS)
    type_col = _find(cols, _TYPE_HINTS)

    if not kwh_col or not (ts_col or date_col):
        raise SystemExit(
            "Could not find usage and date columns.\n"
            f"  columns seen: {cols}\n"
            "  expected a date/datetime column and a usage/kWh column."
        )

    tcol = ts_col or date_col
    raws = [(r.get(tcol) or "").strip() for r in rows]
    # If no value carries a time-of-day, treat the export as daily.
    is_daily = not any(":" in raw for raw in raws if raw)

    if is_daily:
        daily: list[tuple] = []
        for r in rows:
            raw = (r.get(tcol) or "").strip()
            kwh = _num(r.get(kwh_col, ""))
            if not raw or kwh is None:
                continue
            day = _parse_dt(raw).date()
            dollars = _num(r.get(dollar_col, "")) if dollar_col else None
            typ = (r.get(type_col) or "").strip() or None if type_col else None
            daily.append((day, kwh, dollars, typ))
        return "daily", daily

    hourly: list[tuple] = []
    for r in rows:
        raw = (r.get(tcol) or "").strip()
        kwh = _num(r.get(kwh_col, ""))
        if not raw or kwh is None:
            continue
        ts_utc = _parse_dt(raw).replace(tzinfo=NZ).astimezone(UTC)
        hourly.append((ts_utc, kwh))
    return "hourly", hourly


async def load(kind: str, rows: list[tuple], dsn: str, source: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        if kind == "daily":
            await conn.executemany(
                """INSERT INTO meter_daily_usage (day, kwh, dollars, type, source)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (day, source) DO UPDATE
                     SET kwh = EXCLUDED.kwh, dollars = EXCLUDED.dollars,
                         type = EXCLUDED.type""",
                [(d, k, dol, t, source) for (d, k, dol, t) in rows],
            )
        else:
            await conn.executemany(
                """INSERT INTO meter_hourly (ts, kwh, source)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (ts, source) DO UPDATE SET kwh = EXCLUDED.kwh""",
                [(ts, k, source) for (ts, k) in rows],
            )
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a Genesis usage CSV.")
    ap.add_argument("csv", help="path to the exported CSV")
    ap.add_argument("--source", default="genesis", help="source tag stored per row")
    ap.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL", "postgresql://energy:energy@localhost:5432/energy"
        ),
    )
    args = ap.parse_args()

    kind, rows = parse_csv(args.csv)
    if not rows:
        print("No rows parsed — nothing to import.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(load(kind, rows, args.database_url, args.source))
    lo = min(r[0] for r in rows)
    hi = max(r[0] for r in rows)
    total = sum(r[1] for r in rows)
    print(f"Imported {len(rows)} {kind} rows (source={args.source}). "
          f"Range: {lo} .. {hi}. Total: {total:.2f} kWh")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPX Dealer Gamma fetcher for the Plasma widget.

Thin JSON wrapper around the engine in spx_gamma.py. Prints exactly one JSON
line on stdout so the QML side can parse it. Never crashes the widget: every
failure path emits valid JSON with status "error" and exits 0.
"""
import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


def now_iso() -> str:
    return datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def error_result(message: str) -> dict:
    return {
        "status": "error",
        "timestamp": now_iso(),
        "source": "CBOE delayed quotes",
        "spot": None,
        "net_gex": None,
        "regime": None,
        "flip": None,
        "flip_distance": None,
        "flip_distance_pct": None,
        "errors": [{"message": message}],
    }


# --- guarded imports: missing deps must surface as JSON, not a traceback ------
try:
    import numpy as np
    from spx_gamma import (
        compute_spot_gex,
        fetch_cboe_chain,
        find_flip_levels,
        gamma_profile,
        load_chain_from_file,
        parse_chain,
    )
except Exception as exc:  # ImportError or any load-time failure
    emit(error_result(f"Missing Python dependency or import error: {exc}"))
    raise SystemExit(0)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="SPX dealer gamma fetcher (JSON out).")
    ap.add_argument("--max-dte", type=int, default=90,
                    help="only include expiries up to X days (default: 90)")
    ap.add_argument("--spot-only", action="store_true",
                    help="emit only the SPX spot price; skip GEX/flip computation")
    ap.add_argument("--min-oi", type=float, default=0)
    ap.add_argument("--rate", type=float, default=0.045)
    ap.add_argument("--div", type=float, default=0.013)
    ap.add_argument("--spot", type=float, default=None)
    ap.add_argument("--from-file", type=str, default=None,
                    help="load a saved CBOE JSON snapshot instead of the live feed")
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--use-cboe-gamma", action="store_true",
                    help="use CBOE-supplied gamma for spot GEX instead of BS")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    # 1) data
    try:
        if args.from_file:
            raw = load_chain_from_file(args.from_file)
        else:
            raw = fetch_cboe_chain(timeout=args.timeout)
    except Exception as exc:
        emit(error_result(f"Could not load option chain: {exc}"))
        return 0

    # 2a) spot-only: SPX moves intraday, but OI (-> GEX/flip) is EOD. Skip the
    # heavy gamma computation and emit just the price for interval refreshes.
    if args.spot_only:
        try:
            _df, spot = parse_chain(raw, spot_override=args.spot)
        except Exception as exc:
            emit(error_result(f"Could not parse option chain: {exc}"))
            return 0
        emit({
            "status": "ok",
            "mode": "spot",
            "timestamp": now_iso(),
            "source": "CBOE delayed quotes",
            "spot": round(float(spot), 2),
            "errors": [],
        })
        return 0

    # 2) parse + filter
    try:
        df, spot = parse_chain(raw, spot_override=args.spot)
        df = df[(df["iv"] > 0) & (df["oi"] >= args.min_oi)].copy()
        if args.max_dte is not None:
            df = df[df["dte"] <= args.max_dte].copy()
        df = df[df["dte"] >= 0].copy()
        if df.empty:
            emit(error_result("No options left after filtering."))
            return 0
    except Exception as exc:
        emit(error_result(f"Could not parse option chain: {exc}"))
        return 0

    # 3) compute
    try:
        g_spot = compute_spot_gex(df, spot, use_bs=not args.use_cboe_gamma,
                                  r=args.rate, q=args.div)
        total_gex = float(np.sum(g_spot))

        levels, net = gamma_profile(df, spot, r=args.rate, q=args.div)
        flips = find_flip_levels(levels, net)
        flip_near = min(flips, key=lambda f: abs(f - spot)) if flips else None
    except Exception as exc:
        emit(error_result(f"Gamma computation failed: {exc}"))
        return 0

    net_gex_bn = total_gex / 1e9
    flip_distance = (flip_near - spot) if flip_near is not None else None
    flip_distance_pct = ((flip_near / spot - 1.0) * 100.0
                         if flip_near is not None else None)

    emit({
        "status": "ok",
        "timestamp": now_iso(),
        "source": "CBOE delayed quotes",
        "spot": round(float(spot), 2),
        "net_gex": round(net_gex_bn, 3),
        "regime": "positive" if total_gex > 0 else "negative",
        "flip": round(float(flip_near), 1) if flip_near is not None else None,
        "flip_distance": round(float(flip_distance), 1) if flip_distance is not None else None,
        "flip_distance_pct": round(float(flip_distance_pct), 2) if flip_distance_pct is not None else None,
        "n_options": int(len(df)),
        "errors": [],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

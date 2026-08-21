#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPX Dealer Gamma fetcher for the Plasma widget.

Thin JSON wrapper around the engine in spx_gamma.py. Prints exactly one JSON
line on stdout so the QML side can parse it. Never crashes the widget: every
failure path emits valid JSON with status "error" and exits 0.

Modes:
  full      fetch the ~13 MB option chain, compute GEX/flip/walls, cache the
            raw chain. Run once per day after the close (open interest is EOD).
  intraday  fetch the ~540 byte index quote and recompute GEX/flip/walls from
            the cached chain at the *live* spot and with *fresh* time to expiry.
            No chain download. Falls back to "full" when the cache is missing.
  spot      quote only, no gamma math. Light fallback.
"""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Payload keys shared by every response, so QML never sees a missing field.
NULL_FIELDS = (
    "spot", "net_gex", "regime", "flip", "flip_distance", "flip_distance_pct",
    "call_wall", "call_wall_gex", "call_wall_distance",
    "put_wall", "put_wall_gex", "put_wall_distance",
    "iv30", "iv30_change_pct", "quote_time", "feed_time", "data_age_min",
    "chain_time", "chain_age_hours", "wall_min_dte", "n_options",
)


def now_iso() -> str:
    return datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def error_result(message: str) -> dict:
    payload = {
        "status": "error",
        "timestamp": now_iso(),
        "source": "CBOE delayed quotes",
        "errors": [{"message": message}],
    }
    payload.update({key: None for key in NULL_FIELDS})
    return payload


# --- guarded imports: missing deps must surface as JSON, not a traceback ------
try:
    import numpy as np
    from spx_gamma import (
        MAX_IV,
        WALL_MIN_DTE,
        cache_age_hours,
        compute_spot_gex,
        default_cache_path,
        extract_meta,
        extract_spot,
        fetch_cboe_chain,
        fetch_cboe_quote,
        filter_chain,
        find_flip_levels,
        find_walls,
        gamma_profile,
        load_chain_cache,
        load_chain_from_file,
        parse_chain,
        save_chain_cache,
    )
except Exception as exc:  # ImportError or any load-time failure
    emit(error_result(f"Missing Python dependency or import error: {exc}"))
    raise SystemExit(0)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="SPX dealer gamma fetcher (JSON out).")
    ap.add_argument("--mode", choices=("full", "intraday", "spot"), default="full",
                    help="full = download chain, intraday = recompute from cache, "
                         "spot = quote only (default: full)")
    ap.add_argument("--max-dte", type=int, default=90,
                    help="only include expiries up to X days (default: 90)")
    ap.add_argument("--spot-only", action="store_true",
                    help="deprecated alias for --mode spot")
    ap.add_argument("--min-oi", type=float, default=0)
    ap.add_argument("--max-iv", type=float, default=MAX_IV,
                    help="drop quotes above this implied vol (default: 3.0)")
    ap.add_argument("--wall-min-dte", type=int, default=WALL_MIN_DTE,
                    help=f"minimum DTE for put/call walls (default: {WALL_MIN_DTE})")
    ap.add_argument("--rate", type=float, default=0.045)
    ap.add_argument("--div", type=float, default=0.013)
    ap.add_argument("--spot", type=float, default=None)
    ap.add_argument("--from-file", type=str, default=None,
                    help="load a saved CBOE JSON snapshot instead of the live feed")
    ap.add_argument("--cache-file", type=str, default=None,
                    help=f"chain cache path (default: {default_cache_path()})")
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--use-cboe-gamma", action="store_true",
                    help="use CBOE-supplied gamma for spot GEX instead of BS")
    return ap.parse_args()


def meta_fields(meta: dict) -> dict:
    """Data-age and IV30 fields lifted out of a CBOE payload."""
    return {
        "quote_time": meta.get("quote_time"),
        "feed_time": meta.get("feed_time"),
        "data_age_min": meta.get("age_minutes"),
        "iv30": round(meta["iv30"], 2) if meta.get("iv30") is not None else None,
        "iv30_change_pct": (round(meta["iv30_change_pct"], 2)
                            if meta.get("iv30_change_pct") is not None else None),
    }


def chain_meta_fields(raw, cache_path=None):
    """When the chain snapshot itself was produced -- not when we read it."""
    meta = extract_meta(raw)
    return {
        "chain_time": meta.get("feed_time") or meta.get("quote_time"),
        "chain_age_hours": cache_age_hours(cache_path) if cache_path else 0.0,
    }


def compute_payload(raw, args, spot_override, mode, meta, chain_meta):
    """Full gamma math over a chain (live or cached) at the given spot."""
    df, spot = parse_chain(raw, spot_override=spot_override)
    df = filter_chain(df, min_oi=args.min_oi, max_dte=args.max_dte,
                      max_iv=args.max_iv)
    if df.empty:
        return error_result("No options left after filtering.")

    total_gex = float(np.sum(compute_spot_gex(
        df, spot, use_bs=not args.use_cboe_gamma, r=args.rate, q=args.div)))

    levels, net = gamma_profile(df, spot, r=args.rate, q=args.div)
    flips = find_flip_levels(levels, net)
    flip_near = min(flips, key=lambda f: abs(f - spot)) if flips else None

    walls = find_walls(df, spot, r=args.rate, q=args.div,
                       min_dte=args.wall_min_dte)

    def wall_fields(prefix):
        """Strike, exposure (Bn$/1%) and distance to spot for one wall side."""
        strike = walls.get(prefix)
        if strike is None:
            return {prefix: None, prefix + "_gex": None, prefix + "_distance": None}
        gex = walls.get(prefix + "_gex")
        return {
            prefix: round(float(strike), 1),
            prefix + "_gex": round(float(gex) / 1e9, 3) if gex is not None else None,
            prefix + "_distance": round(float(strike) - float(spot), 1),
        }

    payload = {
        "status": "ok",
        "mode": mode,
        "timestamp": now_iso(),
        "source": "CBOE delayed quotes",
        "spot": round(float(spot), 2),
        "net_gex": round(total_gex / 1e9, 3),
        "regime": "positive" if total_gex > 0 else "negative",
        "flip": round(float(flip_near), 1) if flip_near is not None else None,
        "flip_distance": (round(float(flip_near - spot), 1)
                          if flip_near is not None else None),
        "flip_distance_pct": (round((float(flip_near) / spot - 1.0) * 100.0, 2)
                              if flip_near is not None else None),
        "wall_min_dte": walls.get("wall_min_dte"),
        "n_options": int(len(df)),
        "errors": [],
    }
    payload.update(wall_fields("call_wall"))
    payload.update(wall_fields("put_wall"))
    payload.update(meta_fields(meta))
    payload.update(chain_meta)
    return payload


def main() -> int:
    args = parse_args()
    mode = "spot" if args.spot_only else args.mode
    cache_path = args.cache_file or default_cache_path()

    # A saved snapshot always takes the full path; nothing to cache or poll.
    if args.from_file:
        try:
            raw = load_chain_from_file(args.from_file)
        except Exception as exc:
            emit(error_result(f"Could not load snapshot: {exc}"))
            return 0
        try:
            emit(compute_payload(raw, args, args.spot, "full",
                                 extract_meta(raw), chain_meta_fields(raw)))
        except Exception as exc:
            emit(error_result(f"Gamma computation failed: {exc}"))
        return 0

    # ---- intraday: live quote + cached chain, recomputed at the live spot ----
    # Open interest is EOD, but spot moves and time decays. Re-running the math
    # on the cached chain keeps regime, flip and walls consistent with the price
    # on screen instead of freezing the previous close.
    if mode == "intraday":
        try:
            quote = fetch_cboe_quote(timeout=args.timeout)
            spot = extract_spot(quote, spot_override=args.spot)
            meta = extract_meta(quote)
        except Exception as exc:
            emit(error_result(f"Could not load index quote: {exc}"))
            return 0
        try:
            cached = load_chain_cache(cache_path)
        except Exception:
            cached = None      # no cache yet -> fall through to a full fetch
        if cached is not None:
            try:
                emit(compute_payload(cached, args, spot, "intraday", meta,
                                     chain_meta_fields(cached, cache_path)))
            except Exception as exc:
                emit(error_result(f"Gamma computation failed: {exc}"))
            return 0
        mode = "full"

    # ---- spot: quote only ---------------------------------------------------
    if mode == "spot":
        try:
            quote = fetch_cboe_quote(timeout=args.timeout)
            spot = extract_spot(quote, spot_override=args.spot)
            meta = extract_meta(quote)
        except Exception as exc:
            emit(error_result(f"Could not read spot price: {exc}"))
            return 0
        payload = {
            "status": "ok",
            "mode": "spot",
            "timestamp": now_iso(),
            "source": "CBOE delayed quotes",
            "spot": round(float(spot), 2),
            "errors": [],
        }
        payload.update(meta_fields(meta))
        emit(payload)
        return 0

    # ---- full: download the chain, compute, refresh the cache ---------------
    try:
        raw = fetch_cboe_chain(timeout=args.timeout)
    except Exception as exc:
        emit(error_result(f"Could not load option chain: {exc}"))
        return 0
    try:
        payload = compute_payload(raw, args, args.spot, "full",
                                  extract_meta(raw), chain_meta_fields(raw))
    except Exception as exc:
        emit(error_result(f"Gamma computation failed: {exc}"))
        return 0
    # Cache only a chain we could actually compute on.
    if payload.get("status") == "ok":
        try:
            save_chain_cache(raw, cache_path)
        except Exception as exc:
            payload["errors"] = [{"message": f"Chain cache not written: {exc}"}]
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

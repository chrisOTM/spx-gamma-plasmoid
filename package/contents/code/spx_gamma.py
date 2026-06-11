#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPX Dealer Gamma Exposure (GEX) & Gamma Flip Level
====================================================

Berechnet die Netto-Gamma-Exposure der Market Maker (Dealer) fuer den S&P 500
Index (SPX) und ermittelt das "Gamma Flip Level" (Zero-Gamma-Punkt).

Datenquelle:  CBOE Delayed Quotes (kostenlos, kein API-Key noetig)
              https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json
              -> ~15 Min verzoegert; nach Boersenschluss = EOD-Snapshot.
              -> liefert Open Interest, IV und Greeks (inkl. Gamma) je Strike.

Methodik (Standard / "naive GEX" nach SqueezeMetrics):
  * Annahme ueber die Dealer-Positionierung:
        Dealer sind LONG Calls  -> positive Gamma
        Dealer sind SHORT Puts  -> negative Gamma
    Das ist eine MODELLANNAHME, keine Tatsache. Ueber DEALER_LONG_CALLS /
    PUT_SIGN laesst sie sich umdrehen.
  * GEX je Option ($ pro 1% Indexbewegung):
        GEX = sign * Gamma * OpenInterest * 100 * Spot^2 * 0.01
  * Gamma Flip Level: der Indexstand, bei dem die Netto-GEX-Kurve das
    Vorzeichen wechselt. Dazu wird Gamma per Black-Scholes ueber ein Raster
    von Spotpreisen neu berechnet (IV je Strike fix = "sticky strike").

Aufruf:
    python spx_gamma.py
    python spx_gamma.py --max-dte 90 --rate 0.045 --div 0.013
    python spx_gamma.py --spot 5500          # Spot manuell ueberschreiben
    python spx_gamma.py --from-file chain.json   # gespeicherten Snapshot laden

Abhaengigkeiten:
    pip install requests numpy pandas scipy matplotlib
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import norm

# --------------------------------------------------------------------------- #
# Konfiguration / Modellannahmen
# --------------------------------------------------------------------------- #
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
CBOE_SYMBOL = "_SPX"          # SPX-Index bei CBOE
CONTRACT_MULTIPLIER = 100      # 1 SPX-Kontrakt = 100 x Index

# Dealer-Positionierung (Modellannahme, siehe Docstring):
DEALER_LONG_CALLS = True       # True -> Calls liefern positive Dealer-Gamma
# Daraus folgende Vorzeichen:
CALL_SIGN = +1 if DEALER_LONG_CALLS else -1
PUT_SIGN = -CALL_SIGN          # Puts gegengleich (short Puts = negative Gamma)

OSI_RE = re.compile(r"^(?P<root>[A-Z\^_]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


# --------------------------------------------------------------------------- #
# 1) Datenbeschaffung
# --------------------------------------------------------------------------- #
def fetch_cboe_chain(symbol=CBOE_SYMBOL, timeout=30):
    """Laedt den kompletten SPX-Optionschain als JSON von CBOE."""
    import requests
    url = CBOE_URL.format(sym=symbol)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; gamma-calc/1.0)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def load_chain_from_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# 2) Parsing -> DataFrame
# --------------------------------------------------------------------------- #
def parse_chain(raw, spot_override=None):
    """Wandelt das CBOE-JSON in ein bereinigtes DataFrame um und ermittelt Spot."""
    data = raw.get("data", raw)
    options = data.get("options", [])
    if not options:
        raise ValueError("Keine Optionsdaten im JSON gefunden.")

    # Spot bestimmen: mehrere Felder als Fallback (current_price kann 0 sein).
    spot = spot_override
    if spot is None:
        for key in ("current_price", "close", "last", "prev_day_close"):
            val = data.get(key)
            if val and float(val) > 0:
                spot = float(val)
                break
    if not spot or spot <= 0:
        raise ValueError(
            "Spotpreis konnte nicht ermittelt werden. "
            "Bitte mit --spot manuell setzen."
        )

    rows = []
    for opt in options:
        sym = opt.get("option", "")
        m = OSI_RE.match(sym)
        if not m:
            continue
        exp = datetime.strptime("20" + m.group("exp"), "%Y%m%d").date()
        strike = int(m.group("strike")) / 1000.0
        rows.append(
            {
                "symbol": sym,
                "type": "C" if m.group("cp") == "C" else "P",
                "strike": strike,
                "expiry": exp,
                "oi": float(opt.get("open_interest", 0) or 0),
                "iv": float(opt.get("iv", 0) or 0),
                "gamma": float(opt.get("gamma", 0) or 0),  # CBOE-Gamma (je Aktie)
                "volume": float(opt.get("volume", 0) or 0),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Optionssymbole konnten nicht geparst werden.")

    today = datetime.now(timezone.utc).date()
    df["dte"] = (pd.to_datetime(df["expiry"]) - pd.Timestamp(today)).dt.days
    # Restlaufzeit in Jahren; Boersenschluss 16:00 ET -> grob +0.6 Tag-Anteil
    df["T"] = (df["dte"].clip(lower=0) + 0.6) / 365.0
    return df, spot


# --------------------------------------------------------------------------- #
# 3) Black-Scholes-Gamma (fuer das Flip-Profil noetig)
# --------------------------------------------------------------------------- #
def bs_gamma(S, K, T, sigma, r=0.045, q=0.013):
    """Black-Scholes-Gamma je Aktie (identisch fuer Calls und Puts)."""
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        gamma = np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))

    gamma = np.where((T > 0) & (sigma > 0) & np.isfinite(gamma), gamma, 0.0)
    return gamma


# --------------------------------------------------------------------------- #
# 4) GEX-Berechnung
# --------------------------------------------------------------------------- #
def dealer_sign(df):
    """Vorzeichen je Zeile gemaess Dealer-Annahme."""
    return np.where(df["type"].values == "C", CALL_SIGN, PUT_SIGN)


def gex_dollar(gamma, oi, spot, sign):
    """GEX in USD pro 1% Indexbewegung."""
    return sign * gamma * oi * CONTRACT_MULTIPLIER * spot**2 * 0.01


def compute_spot_gex(df, spot, use_bs=False, r=0.045, q=0.013):
    """Aktuelle Netto-GEX am realen Spot. use_bs=True rechnet Gamma per BS neu."""
    if use_bs:
        gamma = bs_gamma(spot, df["strike"].values, df["T"].values,
                         df["iv"].values, r=r, q=q)
    else:
        gamma = df["gamma"].values  # von CBOE geliefert
    sign = dealer_sign(df)
    g = gex_dollar(gamma, df["oi"].values, spot, sign)
    return g


# --------------------------------------------------------------------------- #
# 5) Gamma-Profil & Flip Level
# --------------------------------------------------------------------------- #
def gamma_profile(df, spot, lo=0.80, hi=1.20, steps=400, r=0.045, q=0.013):
    """Netto-GEX ueber ein Spot-Raster (Gamma per BS, IV fix je Strike)."""
    levels = np.linspace(spot * lo, spot * hi, steps)
    sign = dealer_sign(df)
    oi = df["oi"].values
    K = df["strike"].values
    T = df["T"].values
    iv = df["iv"].values

    net = np.empty_like(levels)
    for i, S in enumerate(levels):
        gamma = bs_gamma(S, K, T, iv, r=r, q=q)
        net[i] = np.sum(gex_dollar(gamma, oi, S, sign))
    return levels, net


def find_flip_levels(levels, net):
    """Alle Nulldurchgaenge (linear interpoliert) der Netto-GEX-Kurve."""
    flips = []
    s = np.sign(net)
    idx = np.where(np.diff(s) != 0)[0]
    for i in idx:
        x0, x1 = levels[i], levels[i + 1]
        y0, y1 = net[i], net[i + 1]
        if y1 == y0:
            continue
        flips.append(x0 - y0 * (x1 - x0) / (y1 - y0))  # lineare Interpolation
    # nahe beieinanderliegende Treffer (z.B. exakte Null) zusammenfassen
    dedup = []
    for f in sorted(flips):
        if not dedup or abs(f - dedup[-1]) > 1e-6:
            dedup.append(f)
    return dedup


# --------------------------------------------------------------------------- #
# 6) Ausgabe / Reporting
# --------------------------------------------------------------------------- #
def per_strike_table(df, spot, r, q):
    """Netto-GEX je Strike (ueber alle Laufzeiten aggregiert), BS-Gamma."""
    gamma = bs_gamma(spot, df["strike"].values, df["T"].values,
                     df["iv"].values, r=r, q=q)
    sign = dealer_sign(df)
    df = df.copy()
    df["gex"] = gex_dollar(gamma, df["oi"].values, spot, sign)
    agg = df.groupby("strike", as_index=False)["gex"].sum()
    return agg.sort_values("strike")


def make_chart(levels, net, flips, spot, agg, outfile="spx_gamma.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[Hinweis] matplotlib nicht installiert -> kein Chart.")
        return None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9))

    # Profil
    ax1.plot(levels, net / 1e9, lw=1.6)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.axvline(spot, color="tab:blue", ls="--", lw=1, label=f"Spot {spot:,.0f}")
    for f in flips:
        ax1.axvline(f, color="tab:red", ls="--", lw=1,
                    label=f"Gamma Flip {f:,.0f}")
    ax1.set_title("SPX Dealer Gamma Profil")
    ax1.set_xlabel("Indexstand")
    ax1.set_ylabel("Netto-GEX (Mrd. $ / 1%)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    # Per-Strike (auf Spot-Umgebung beschnitten)
    near = agg[(agg["strike"] > spot * 0.85) & (agg["strike"] < spot * 1.15)]
    colors = np.where(near["gex"] >= 0, "tab:green", "tab:red")
    ax2.bar(near["strike"], near["gex"] / 1e9, width=8, color=colors)
    ax2.axvline(spot, color="tab:blue", ls="--", lw=1)
    ax2.axhline(0, color="black", lw=0.8)
    ax2.set_title("Netto-GEX je Strike")
    ax2.set_xlabel("Strike")
    ax2.set_ylabel("GEX (Mrd. $ / 1%)")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(outfile, dpi=120)
    print(f"[OK] Chart gespeichert: {outfile}")
    return outfile


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="SPX Dealer Gamma & Gamma Flip Level")
    ap.add_argument("--max-dte", type=int, default=None,
                    help="nur Laufzeiten bis X Tage einbeziehen (Default: alle)")
    ap.add_argument("--min-oi", type=float, default=0,
                    help="Mindest-Open-Interest je Option")
    ap.add_argument("--rate", type=float, default=0.045, help="risikofreier Zins")
    ap.add_argument("--div", type=float, default=0.013, help="Dividendenrendite SPX")
    ap.add_argument("--spot", type=float, default=None, help="Spot manuell setzen")
    ap.add_argument("--from-file", type=str, default=None,
                    help="JSON-Snapshot statt Live-Abruf laden")
    ap.add_argument("--save-json", type=str, default=None,
                    help="Roh-JSON in Datei sichern")
    ap.add_argument("--use-cboe-gamma", action="store_true",
                    help="fuer Spot-GEX das von CBOE gelieferte Gamma nutzen")
    ap.add_argument("--no-chart", action="store_true")
    args = ap.parse_args()

    # Daten holen
    if args.from_file:
        raw = load_chain_from_file(args.from_file)
        print(f"[OK] Snapshot geladen: {args.from_file}")
    else:
        print("[..] Lade CBOE-Daten ...")
        raw = fetch_cboe_chain()
        if args.save_json:
            with open(args.save_json, "w", encoding="utf-8") as fh:
                json.dump(raw, fh)
            print(f"[OK] Roh-JSON gesichert: {args.save_json}")

    df, spot = parse_chain(raw, spot_override=args.spot)

    # Filter
    df = df[(df["iv"] > 0) & (df["oi"] >= args.min_oi)].copy()
    if args.max_dte is not None:
        df = df[df["dte"] <= args.max_dte].copy()
    df = df[df["dte"] >= 0].copy()
    if df.empty:
        sys.exit("Nach Filterung keine Optionen uebrig.")

    # Spot-GEX
    g_spot = compute_spot_gex(df, spot, use_bs=not args.use_cboe_gamma,
                              r=args.rate, q=args.div)
    total_gex = float(np.sum(g_spot))

    # Flip-Profil
    levels, net = gamma_profile(df, spot, r=args.rate, q=args.div)
    flips = find_flip_levels(levels, net)
    flip_near = min(flips, key=lambda f: abs(f - spot)) if flips else None

    # Per-Strike
    agg = per_strike_table(df, spot, r=args.rate, q=args.div)

    # Report
    print("\n" + "=" * 58)
    print(f"  SPX Dealer Gamma Report   ({datetime.now():%Y-%m-%d %H:%M})")
    print("=" * 58)
    print(f"  Spot (Index)            : {spot:,.2f}")
    print(f"  Optionen einbezogen     : {len(df):,}")
    print(f"  Summe Open Interest     : {df['oi'].sum():,.0f}")
    print(f"  Dealer-Annahme          : "
          f"{'long Calls / short Puts' if DEALER_LONG_CALLS else 'short Calls / long Puts'}")
    print("-" * 58)
    print(f"  Netto Dealer-GEX        : {total_gex/1e9:+.3f} Mrd. $ / 1%")
    state = "POSITIV (vola-daempfend)" if total_gex > 0 else "NEGATIV (vola-verstaerkend)"
    print(f"  Gamma-Regime            : {state}")
    if flip_near is not None:
        print(f"  Gamma Flip Level        : {flip_near:,.0f}")
        print(f"  Abstand zum Spot        : {flip_near - spot:+,.0f} "
              f"({(flip_near/spot - 1)*100:+.2f} %)")
        if len(flips) > 1:
            print(f"  weitere Nulldurchgaenge : "
                  f"{', '.join(f'{f:,.0f}' for f in flips)}")
    else:
        print("  Gamma Flip Level        : kein Nulldurchgang im Raster gefunden")

    # groesste Gamma-Strikes
    top = agg.reindex(agg["gex"].abs().sort_values(ascending=False).index).head(8)
    print("-" * 58)
    print("  Groesste GEX-Strikes (Mrd. $ / 1%):")
    for _, row in top.iterrows():
        print(f"     {row['strike']:>8,.0f}  {row['gex']/1e9:+8.3f}")
    print("=" * 58 + "\n")

    # CSV-Export
    agg.assign(gex_bn=agg["gex"] / 1e9).to_csv("spx_gex_per_strike.csv", index=False)
    print("[OK] Per-Strike-Tabelle: spx_gex_per_strike.csv")

    if not args.no_chart:
        make_chart(levels, net, flips, spot, agg)


if __name__ == "__main__":
    main()

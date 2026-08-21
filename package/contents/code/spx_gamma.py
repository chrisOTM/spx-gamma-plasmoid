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
  * Restlaufzeit T: echte Stunden bis zum Settlement in US-Eastern-Zeit.
    SPX-Monatsverfall (Root "SPX") ist AM-settled (09:30 ET), SPXW und alles
    Uebrige PM-settled (16:00 ET). Bereits gesettelte Laufzeiten fallen raus --
    sonst schleppt der EOD-Snapshot das verfallene 0DTE-Open-Interest mit.
  * IV wird nach oben gekappt (MAX_IV): abgelaufene/illiquide Zeilen liefern
    im CBOE-Feed IVs bis ~800 %, die nichts in der Gamma-Summe verloren haben.

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
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import norm

# --------------------------------------------------------------------------- #
# Konfiguration / Modellannahmen
# --------------------------------------------------------------------------- #
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
# Reiner Index-Quote ohne Optionschain: ~540 Byte statt ~14 MB. Gleiche
# "data"-Struktur wie oben, nur ohne "options" -> extract_spot() passt auf beide.
CBOE_QUOTE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"
CBOE_SYMBOL = "_SPX"          # SPX-Index bei CBOE
CONTRACT_MULTIPLIER = 100      # 1 SPX-Kontrakt = 100 x Index

# Dealer-Positionierung (Modellannahme, siehe Docstring):
DEALER_LONG_CALLS = True       # True -> Calls liefern positive Dealer-Gamma
# Daraus folgende Vorzeichen:
CALL_SIGN = +1 if DEALER_LONG_CALLS else -1
PUT_SIGN = -CALL_SIGN          # Puts gegengleich (short Puts = negative Gamma)

# Zeitrechnung: alles in US-Eastern, weil Settlement daran haengt.
ET = ZoneInfo("America/New_York")
SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0
AM_SETTLED_ROOTS = {"SPX"}     # Monatsverfall, Settlement auf den Opening-Print
AM_SETTLE = dtime(9, 30)
PM_SETTLE = dtime(16, 0)
# Numerischer Boden fuer T (1 Stunde): BS-Gamma divergiert fuer T -> 0, eine
# einzelne ATM-Zeile kurz vor Settlement wuerde sonst die Summe dominieren.
MIN_T_YEARS = 1.0 / (365.0 * 24.0)
# Obergrenze fuer plausible IV (300 %).
MAX_IV = 3.0

OSI_RE = re.compile(r"^(?P<root>[A-Z\^_]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


# --------------------------------------------------------------------------- #
# 1) Datenbeschaffung
# --------------------------------------------------------------------------- #
def _fetch_json(url, timeout):
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (compatible; gamma-calc/1.0)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_cboe_chain(symbol=CBOE_SYMBOL, timeout=30):
    """Laedt den kompletten SPX-Optionschain als JSON von CBOE (~14 MB)."""
    return _fetch_json(CBOE_URL.format(sym=symbol), timeout)


def fetch_cboe_quote(symbol=CBOE_SYMBOL, timeout=30):
    """Laedt nur den Index-Quote (~540 Byte) -- fuer reine Spot-Updates.

    Open Interest aktualisiert einmal taeglich, GEX und Flip bleiben zwischen
    den EOD-Snapshots konstant. Intraday muss deshalb nur der Preis nachgezogen
    werden, und dafuer den kompletten Chain zu laden waere Verschwendung.
    """
    return _fetch_json(CBOE_QUOTE_URL.format(sym=symbol), timeout)


def load_chain_from_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# 2) Parsing -> DataFrame
# --------------------------------------------------------------------------- #
def extract_spot(raw, spot_override=None):
    """Spot aus einem CBOE-JSON ziehen -- Chain- wie Quote-Antwort.

    Mehrere Felder als Fallback, weil current_price ausserhalb der Handelszeit
    0 sein kann.
    """
    if spot_override is not None:
        spot = spot_override
    else:
        data = raw.get("data", raw)
        spot = None
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
    return float(spot)


def parse_chain(raw, spot_override=None):
    """Wandelt das CBOE-JSON in ein bereinigtes DataFrame um und ermittelt Spot."""
    data = raw.get("data", raw)
    options = data.get("options", [])
    if not options:
        raise ValueError("Keine Optionsdaten im JSON gefunden.")

    spot = extract_spot(raw, spot_override=spot_override)

    now_et = datetime.now(ET)
    today_et = now_et.date()

    rows = []
    for opt in options:
        sym = opt.get("option", "")
        m = OSI_RE.match(sym)
        if not m:
            continue
        exp = datetime.strptime("20" + m.group("exp"), "%Y%m%d").date()
        strike = int(m.group("strike")) / 1000.0
        root = m.group("root")
        settle = AM_SETTLE if root in AM_SETTLED_ROOTS else PM_SETTLE
        settle_dt = datetime.combine(exp, settle, tzinfo=ET)
        rows.append(
            {
                "symbol": sym,
                "root": root,
                "type": "C" if m.group("cp") == "C" else "P",
                "strike": strike,
                "expiry": exp,
                # Restlaufzeit in Jahren bis zum echten Settlement-Zeitpunkt.
                # Negativ = bereits gesettelt -> faellt in filter_chain() raus.
                "T": (settle_dt - now_et).total_seconds() / SECONDS_PER_YEAR,
                "dte": (exp - today_et).days,
                "oi": float(opt.get("open_interest", 0) or 0),
                "iv": float(opt.get("iv", 0) or 0),
                "gamma": float(opt.get("gamma", 0) or 0),  # CBOE-Gamma (je Aktie)
                "volume": float(opt.get("volume", 0) or 0),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("Optionssymbole konnten nicht geparst werden.")
    return df, spot


def filter_chain(df, min_oi=0.0, max_dte=None, max_iv=MAX_IV):
    """Gemeinsamer Filter fuer CLI und Widget.

    * wirft bereits gesettelte Laufzeiten raus (T <= 0) -- ohne das schleppt der
      EOD-Snapshot das am selben Tag verfallene 0DTE-Open-Interest weiter mit;
    * kappt IV nach oben (Muellquotes bis ~800 % im CBOE-Feed);
    * setzt danach den numerischen Boden MIN_T_YEARS auf T.
    """
    out = df[
        (df["iv"] > 0)
        & (df["iv"] <= max_iv)
        & (df["oi"] >= min_oi)
        & (df["T"] > 0)
    ].copy()
    if max_dte is not None:
        out = out[out["dte"] <= max_dte].copy()
    out["T"] = out["T"].clip(lower=MIN_T_YEARS)
    return out


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


def find_walls(df, spot, r=0.045, q=0.013):
    """Put Wall und Call Wall: die Strikes mit der groessten Gamma-Exposure.

    Call Wall = Strike >= Spot mit der groessten Call-Gamma-Exposure,
    Put Wall  = Strike <= Spot mit der groessten Put-Gamma-Exposure.

    Anders als bei der Netto-GEX wird hier je Seite getrennt und OHNE
    Dealer-Vorzeichen summiert -- gesucht ist der Betrag der aufgestauten
    Gamma-Masse, nicht ihre Richtung. Gamma kommt per Black-Scholes am realen
    Spot (identische Basis wie per_strike_table), damit weit entfernte Strikes
    von selbst gegen 0 gedaempft werden; ein zusaetzliches Strike-Fenster
    braucht es deshalb nicht.

    Rueckgabe: dict mit call_wall/put_wall (Strike) und den zugehoerigen
    Exposures in USD pro 1 % Indexbewegung. Fehlt eine Seite komplett, sind
    ihre Felder None.
    """
    out = {"call_wall": None, "call_wall_gex": None,
           "put_wall": None, "put_wall_gex": None}
    if df.empty:
        return out

    gamma = bs_gamma(spot, df["strike"].values, df["T"].values,
                     df["iv"].values, r=r, q=q)
    work = df.copy()
    work["wall_gex"] = gex_dollar(gamma, work["oi"].values, spot, sign=1)

    def _peak(rows):
        if rows.empty:
            return None, None
        agg = rows.groupby("strike", as_index=False)["wall_gex"].sum()
        agg = agg[agg["wall_gex"] > 0]
        if agg.empty:
            return None, None
        top = agg.loc[agg["wall_gex"].idxmax()]
        return float(top["strike"]), float(top["wall_gex"])

    calls = work[(work["type"] == "C") & (work["strike"] >= spot)]
    puts = work[(work["type"] == "P") & (work["strike"] <= spot)]
    out["call_wall"], out["call_wall_gex"] = _peak(calls)
    out["put_wall"], out["put_wall_gex"] = _peak(puts)
    return out


def make_chart(levels, net, flips, spot, agg, walls=None, outfile="spx_gamma.png"):
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
    if walls:
        if walls.get("put_wall"):
            ax2.axvline(walls["put_wall"], color="tab:purple", ls=":", lw=1.4,
                        label=f"Put Wall {walls['put_wall']:,.0f}")
        if walls.get("call_wall"):
            ax2.axvline(walls["call_wall"], color="tab:orange", ls=":", lw=1.4,
                        label=f"Call Wall {walls['call_wall']:,.0f}")
        ax2.legend(fontsize=8)
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
    ap.add_argument("--max-iv", type=float, default=MAX_IV,
                    help=f"IV-Obergrenze, Default {MAX_IV:g} (= 300 %%)")
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
    df = filter_chain(df, min_oi=args.min_oi, max_dte=args.max_dte,
                      max_iv=args.max_iv)
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

    # Put/Call Wall
    walls = find_walls(df, spot, r=args.rate, q=args.div)

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
    print("-" * 58)
    for label, key in (("Call Wall", "call_wall"), ("Put Wall", "put_wall")):
        strike = walls[key]
        if strike is None:
            print(f"  {label:<24}: keine {label.split()[0]}-Strikes gefunden")
            continue
        print(f"  {label:<24}: {strike:,.0f}  "
              f"({walls[key + '_gex']/1e9:.3f} Mrd. $ / 1%)")
        print(f"  {'Abstand zum Spot':<24}: {strike - spot:+,.0f} "
              f"({(strike/spot - 1)*100:+.2f} %)")

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
        make_chart(levels, net, flips, spot, agg, walls=walls)


if __name__ == "__main__":
    main()

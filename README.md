# SPX Dealer Gamma — KDE Plasma 6 Plasmoid

A small Plasma 6 panel widget that shows, at a glance:

- **SPX spot price** (CBOE delayed quotes, ~15 min; EOD snapshot after close)
- **Net dealer gamma exposure (GEX)** in Bn$ per 1% index move, with regime
  (positive = vol-dampening, negative = vol-amplifying)
- **Gamma flip level** (zero-gamma point) and its distance to spot
- **Put wall / call wall** — the strikes carrying the largest one-sided
  gamma exposure below and above spot, with their distance to spot

The gamma math is the engine in `package/contents/code/spx_gamma.py`
(SqueezeMetrics-style naive GEX, Black-Scholes gamma, zero-crossing flip).
`fetch_gamma.py` wraps it and prints one JSON line for the QML side.

## Screenshots

In a panel:

<img width="432" height="330" alt="SPX Dealer Gamma in a Plasma panel" src="https://github.com/user-attachments/assets/685f11ec-388d-4662-93b4-3e2836beac26" />

Expanded view — all numbers plus status bar:

![Expanded view](docs/full-view.png)

## Panel display modes

Switchable in the widget settings (**Panel display**). Colour follows the gamma
regime: green = positive (vol-dampening), red = negative (vol-amplifying).

| 1. SPX price + regime color | 2. Net GEX value | 3. Regime glyph + price |
|:---:|:---:|:---:|
| ![Price + regime](docs/compact_0.png) | ![Net GEX](docs/compact_1.png) | ![Regime glyph](docs/compact_2.png) |
| spot price tinted by regime, flip distance below | net GEX colored by sign, spot below | ▲ / ▼ glyph for the regime, spot below |

The expanded view shows all numbers: SPX, Net GEX + regime, gamma flip and Δ to
spot, call wall and put wall, plus a status bar.

## Dependencies

```
pip install requests numpy pandas scipy
```

`python3` must be on PATH. If a dependency is missing, the widget shows a clear
error instead of failing silently.

## Install

```bash
bash scripts/install.sh           # kpackagetool6 --install
# then add "SPX Dealer Gamma" from the Plasma widget browser, or:
plasmawindowed com.chrisotm.spxgamma
```

Update after changes:

```bash
bash scripts/upgrade.sh
# or, for dev (auto install/upgrade + launch):
bash scripts/dev-reload.sh
```

Remove:

```bash
bash scripts/uninstall.sh
```

## Settings

- **Daily EOD refresh** (US Eastern time, default 16:30 ET) — one fetch per
  weekday after the close, since Open Interest only updates once a day. This is
  the only time the ~14 MB option chain is downloaded. Use the refresh button to
  force it.
- **Intraday SPX price refresh** (default 15 min, US market hours only) — pulls
  the ~540 byte CBOE index quote and updates the spot price and the distances to
  the flip level and to both walls. GEX, the flip level and the wall strikes
  themselves stay fixed until the next EOD refresh, because they depend on Open
  Interest. Expanding the widget triggers
  the same light refresh.
- **Panel display** (the three compact modes above)
- **Max days to expiry** (default 90) — caps which option expiries feed the GEX.
  The flip level depends on this window: on a sample snapshot the 90-day cap
  gave 7696 against 7668 across all expiries.

## Manual test of the fetcher

```bash
cd package/contents/code
python3 fetch_gamma.py                       # live CBOE, full GEX + flip
python3 fetch_gamma.py --spot-only           # light index quote only
python3 fetch_gamma.py --from-file chain.json # saved snapshot
```

A saved snapshot can be produced with the engine directly:
`python3 spx_gamma.py --save-json chain.json`.

## Notes

The dealer positioning model (long calls / short puts) is an **assumption**, not
a fact — see the docstring in `spx_gamma.py`. The flip level is the nearest
zero-crossing of the GEX-vs-spot profile to the current spot.

The walls are computed per side and **without** the dealer sign: what matters is
the size of the piled-up gamma, not its direction. The call wall is the strike at
or above spot with the largest summed call gamma exposure, the put wall the
strike at or below spot with the largest put gamma exposure. Gamma comes from
Black-Scholes at the real spot, so distant strikes damp towards zero on their own
and no extra strike window is needed. Both use the same `--max-dte` window as the
GEX. A side with no eligible strikes reports `null` and shows as `—`.

Time to expiry is measured to the actual settlement instant in US Eastern time —
09:30 ET for the AM-settled SPX monthlies, 16:00 ET for SPXW and the rest — so
contracts that have already settled drop out of the EOD snapshot instead of
contributing phantom gamma. Quotes above 300% implied vol are discarded
(`--max-iv`).

## License

MIT.

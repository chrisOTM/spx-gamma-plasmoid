# SPX Dealer Gamma — KDE Plasma 6 Plasmoid

A small Plasma 6 panel widget that shows, at a glance:

- **SPX spot price** (CBOE delayed quotes, ~15 min; EOD snapshot after close)
- **Net dealer gamma exposure (GEX)** in Bn$ per 1% index move, with regime
  (positive = vol-dampening, negative = vol-amplifying)
- **Gamma flip level** (zero-gamma point) and its distance to spot
- **Put wall / call wall** — the strikes carrying the largest one-sided
  gamma exposure below and above spot, with their distance to spot
- **IV30** — CBOE's 30-day implied vol and its daily change, which ships with
  the same quote. Regime alone is not a decision: positive gamma at IV30 12
  reads differently than at IV30 25
- **Data age** — how old the underlying CBOE print is, not how long ago the
  widget ran. A fetch on a market holiday returns a fresh clock on stale numbers

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
- **Intraday refresh** (default 15 min, US market hours only) — pulls the
  ~540 byte CBOE index quote and then **recomputes GEX, regime, flip level and
  both walls from the locally cached chain** at the live spot and with freshly
  decayed time to expiry. No chain download. Open interest stays EOD — but
  everything that does move during the session now follows the price instead of
  freezing at the previous close. Expanding the widget triggers the same
  refresh.
- **Panel display** (the three compact modes above)
- **Wall minimum days to expiry** (default 1) — drops same-day expiries from the
  put/call walls. Their open interest is gone by the close and its high gamma
  inflates strikes near spot, while a wall is read as a multi-day level. Set to
  0 to count them. On real SPX data this is a second-order correction: the walls
  are dominated by the next monthly expiry either way.
- **Max days to expiry** (default 90) — caps which option expiries feed the GEX.
  The flip level depends on this window: on a sample snapshot the 90-day cap
  gave 7696 against 7668 across all expiries.

## Manual test of the fetcher

```bash
cd package/contents/code
python3 fetch_gamma.py --mode full            # live chain, full GEX + flip, refreshes the cache
python3 fetch_gamma.py --mode intraday        # live quote + cached chain, recomputed at the live spot
python3 fetch_gamma.py --mode spot            # index quote only, no gamma math
python3 fetch_gamma.py --from-file chain.json # saved snapshot
```

`--mode intraday` falls back to a full download when no cache exists, so it is
also the right call on a cold start. The cache lives at
`${XDG_CACHE_HOME:-~/.cache}/spx-gamma-plasmoid/chain.json.gz` (~1.6 MB gzipped,
one file, overwritten by each full fetch).

A saved snapshot can be produced with the engine directly:
`python3 spx_gamma.py --save-json chain.json`.

## Notes

The dealer positioning model (long calls / short puts) is an **assumption**, not
a fact — see the docstring in `spx_gamma.py`. The flip level is the nearest
zero-crossing of the GEX-vs-spot profile to the current spot.

Only open interest is end-of-day. Spot, time to expiry and therefore the whole
GEX curve are not, so the intraday refresh re-runs the full computation against
the cached chain. Without that, the regime badge can stay green while spot has
already traded through the flip level shown right below it.

The walls are computed per side and **without** the dealer sign: what matters is
the size of the piled-up gamma, not its direction. The call wall is the strike at
or above spot with the largest summed call gamma exposure, the put wall the
strike at or below spot with the largest put gamma exposure. Gamma comes from
Black-Scholes at the real spot, so distant strikes damp towards zero on their own
and no extra strike window is needed. Both use the same `--max-dte` window as the
GEX, plus a `--wall-min-dte` floor (default 1) that keeps same-day expiries out. A side with no eligible strikes reports `null` and shows as `—`.

Time to expiry is measured to the actual settlement instant in US Eastern time —
09:30 ET for the AM-settled SPX monthlies, 16:00 ET for SPXW and the rest — so
contracts that have already settled drop out of the EOD snapshot instead of
contributing phantom gamma. Quotes above 300% implied vol are discarded
(`--max-iv`).

## License

MIT.

# Architecture

```
panel widget (QML)                      python (subprocess)
─────────────────                       ───────────────────
main.qml
  Plasma5Support.DataSource ──exec──►  fetch_gamma.py --mode full|intraday|spot
  (engine: "executable")                 │ argparse: --max-dte --wall-min-dte …
                                          │ guarded imports (numpy/scipy/…)
  Timer (1-min tick → daily EOD fetch)    ▼
  Timer (15-min tick → --mode intraday) spx_gamma.py  (engine, reused as library)
  fetchTimeout (30 s)                     fetch_cboe_chain() ─► chain JSON ~13 MB
                                          fetch_cboe_quote() ─► quote JSON ~540 B
                                          save/load_chain_cache() ─► ~1.6 MB .gz
  onNewData(stdout) ◄──one JSON line──    parse_chain()      ─► DataFrame + spot
  handleFetcherOutput()                   filter_chain()     ─► live, sane rows
    JSON.parse → props                    extract_meta()     ─► data age, IV30
    applyMeta()                           compute_spot_gex() ─► net GEX
                                          gamma_profile()    ─► GEX-vs-spot curve
  compactRepresentation                   find_flip_levels() ─► zero crossings
    3 modes (configuration.compactMode)   find_walls()       ─► put / call wall
  fullRepresentation                    emit JSON:
    SPX / GEX / regime / IV30              {spot, net_gex, regime, flip,
    flip / Δ / call wall / put wall         flip_distance, flip_distance_pct,
    + StatusBar.qml (status, data age)      call_wall…, put_wall…, iv30,
                                            quote_time, data_age_min,
                                            chain_time, chain_age_hours,
                                            wall_min_dte, status, errors}
```

## Fetch modes

| mode | network | computes | when |
|---|---|---|---|
| `full` | chain, ~13 MB | everything, then writes the cache | once per weekday after the close, and on the refresh button |
| `intraday` | quote, ~540 B | everything, from the cached chain at the live spot | every N minutes during US market hours, on expand, on startup |
| `spot` | quote, ~540 B | nothing | light fallback |

Only open interest is end-of-day. Spot and time to expiry are not, so `intraday`
re-runs the whole computation against the cached chain rather than freezing the
previous close's numbers. Recomputing costs ~1.5 s of CPU and no chain download.
Without it the regime badge can read POSITIVE while spot has already traded
through the flip level displayed one row below.

`intraday` falls back to `full` when the cache is missing or unreadable, which
also makes it the correct call on a cold start — a plasmashell restart no longer
re-downloads the chain.

## Contract

`fetch_gamma.py` always prints exactly one JSON line and exits 0, even on
failure (status `"error"`, message in `errors[]`). The error payload carries the
same keys as a successful one, all `null`, so the QML side never sees a missing
field. This mirrors `vix-term-structure-plasmoid` so the QML never has to handle
a crash, only a status. Stale data stays on screen during refresh/error
(`hasData` / `lastSuccessfulUpdate`).

Two clocks are reported and must not be confused: `timestamp` is when the
fetcher ran, `quote_time` / `data_age_min` describe how old the CBOE print
itself is. The status bar shows the latter, because a fetch on a market holiday
returns a fresh clock on stale numbers.

## Files

- `package/contents/code/spx_gamma.py` — the GEX/flip engine (copied from
  `_snippets/spx_gamma.py`; its `main()` CLI still works standalone). Also owns
  the chain cache and `extract_meta()`.
- `package/contents/code/fetch_gamma.py` — thin JSON wrapper, imports the engine
  as a module, owns the three fetch modes.
- `package/contents/ui/main.qml` — widget: state, both representations, data
  source, timers, JSON parsing.
- `package/contents/ui/StatusBar.qml` — status / data age / EOD refresh time line.
- `package/contents/ui/configGeneral.qml` + `config/main.xml` + `config.qml` —
  settings: daily EOD refresh time (ET), intraday interval, panel display mode,
  max DTE, wall minimum DTE.

## Data source

CBOE delayed quotes, free and without an API key, ~15 min delayed (EOD snapshot
after close):

- `.../delayed_quotes/options/_SPX.json` — full chain, ~13 MB, open interest, IV
  and greeks per strike. Fetched once per weekday for the EOD GEX and flip, then
  cached gzipped.
- `.../delayed_quotes/quotes/_SPX.json` — index quote only, ~540 bytes, same
  `data` shape minus `options`. Carries `iv30`, `last_trade_time` and the feed
  `timestamp`. Used by `--mode intraday`/`--mode spot`, so a price refresh costs
  ~1/25000 of a chain download.

## Chain cache

`${XDG_CACHE_HOME:-~/.cache}/spx-gamma-plasmoid/chain.json.gz` — the raw chain
JSON, gzipped (~13 MB → ~1.6 MB), written atomically and only after the fetcher
could actually compute on it. The raw payload is kept rather than a reduced
frame so `parse_chain()` recomputes time to expiry from scratch on every read.

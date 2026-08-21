# Architecture

```
panel widget (QML)                      python (subprocess)
─────────────────                       ───────────────────
main.qml
  Plasma5Support.DataSource ──exec──►  fetch_gamma.py
  (engine: "executable")                 │ argparse: --max-dte --timeout ...
                                          │ guarded imports (numpy/scipy/...)
  Timer (1-min tick → daily EOD fetch)    ▼
  Timer (15-min tick → --spot-only)    spx_gamma.py  (engine, reused as library)
  fetchTimeout (30 s)                     fetch_cboe_chain() ─► chain JSON ~14 MB
                                          fetch_cboe_quote() ─► quote JSON ~540 B
  onNewData(stdout) ◄──one JSON line──    parse_chain()      ─► DataFrame + spot
  handleFetcherOutput()                   filter_chain()     ─► live, sane rows
    JSON.parse → props                    compute_spot_gex() ─► net GEX
                                          gamma_profile()    ─► GEX-vs-spot curve
                                          find_flip_levels() ─► zero crossings
  compactRepresentation                 emit JSON:
    3 modes (configuration.compactMode)   {spot, net_gex, regime, flip,
  fullRepresentation                       flip_distance, flip_distance_pct,
    SPX / GEX / regime / flip / Δ          status, errors}
    + StatusBar.qml
```

## Contract

`fetch_gamma.py` always prints exactly one JSON line and exits 0, even on
failure (status `"error"`, message in `errors[]`). This mirrors
`vix-term-structure-plasmoid` so the QML never has to handle a crash, only a
status. Stale data stays on screen during refresh/error (`hasData` /
`lastSuccessfulUpdate`).

## Files

- `package/contents/code/spx_gamma.py` — the GEX/flip engine (copied from
  `_snippets/spx_gamma.py`; its `main()` CLI still works standalone).
- `package/contents/code/fetch_gamma.py` — thin JSON wrapper, imports the engine
  as a module.
- `package/contents/ui/main.qml` — widget: state, both representations, data
  source, timers, JSON parsing.
- `package/contents/ui/StatusBar.qml` — status / last update / EOD refresh time line.
- `package/contents/ui/configGeneral.qml` + `config/main.xml` + `config.qml` —
  settings: daily EOD refresh time (ET), panel display mode, max DTE.

## Data source

CBOE delayed quotes, free and without an API key, ~15 min delayed (EOD snapshot
after close):

- `.../delayed_quotes/options/_SPX.json` — full chain, ~14 MB, open interest, IV
  and greeks per strike. Fetched once per weekday for the EOD GEX and flip.
- `.../delayed_quotes/quotes/_SPX.json` — index quote only, ~540 bytes, same
  `data` shape minus `options`. Used by `--spot-only` for the intraday price
  poll, so a price refresh costs ~1/25000 of a chain download.

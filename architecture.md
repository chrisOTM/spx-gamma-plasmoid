# Architecture

```
panel widget (QML)                      python (subprocess)
─────────────────                       ───────────────────
main.qml
  Plasma5Support.DataSource ──exec──►  fetch_gamma.py
  (engine: "executable")                 │ argparse: --max-dte --timeout ...
                                          │ guarded imports (numpy/scipy/...)
  Timer (refresh, default 15 min)         ▼
  fetchTimeout (30 s)                  spx_gamma.py  (engine, reused as library)
                                          fetch_cboe_chain() ─► CBOE delayed JSON
  onNewData(stdout) ◄──one JSON line──    parse_chain()      ─► DataFrame + spot
  handleFetcherOutput()                   compute_spot_gex() ─► net GEX
    JSON.parse → props                    gamma_profile()    ─► GEX-vs-spot curve
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
- `package/contents/ui/StatusBar.qml` — status / last update / interval line.
- `package/contents/ui/configGeneral.qml` + `config/main.xml` + `config.qml` —
  settings: refresh interval, panel display mode, max DTE.

## Data source

CBOE delayed quotes: `https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json`
— free, no API key, ~15 min delayed (EOD snapshot after close). Provides open
interest, IV and greeks per strike.

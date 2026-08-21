import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    Plasmoid.title: i18n("SPX Dealer Gamma")
    Plasmoid.icon: "office-chart-line"
    toolTipMainText: Plasmoid.title
    toolTipSubText: i18n("SPX dealer GEX, gamma flip & put/call walls via CBOE delayed quotes")

    // ── State ────────────────────────────────────────────────────────────────
    property real   spot:            NaN
    property real   netGex:          NaN     // Bn$ per 1%
    property string regime:          ""      // "positive" | "negative"
    property real   flip:            NaN
    property real   flipDistance:    NaN
    property real   flipDistancePct: NaN
    // Put/Call Wall: strikes with the largest one-sided gamma exposure.
    // Strikes are EOD-fixed (OI-driven); only the distances follow spot.
    property real   callWall:         NaN
    property real   callWallGex:      NaN     // Bn$ per 1%
    property real   callWallDistance: NaN
    property real   putWall:          NaN
    property real   putWallGex:       NaN
    property real   putWallDistance:  NaN

    // IV30 and data age ride along in every CBOE payload -- regime alone is not
    // a decision, positive gamma at IV30 12 reads differently than at IV30 25.
    property real   iv30:            NaN
    property real   iv30ChangePct:   NaN
    // Age of the *data* (last index print), not of the fetch. A fresh fetch on
    // a holiday still returns stale data; only this distinguishes the two.
    property real   dataAgeMin:      NaN
    property real   chainAgeHours:   NaN
    property string dataMode:        ""      // "full" | "intraday" | "spot"

    property bool   hasData:         false
    property string status:          "loading"
    property string errorMessage:    ""
    property string lastUpdate:           ""
    property string lastSuccessfulUpdate: ""
    property bool   isRefreshing:    false
    // Daily EOD refresh time (US Eastern). OI updates once per day -> one fetch/day.
    property int    eodRefreshHourEt:   plasmoid.configuration.eodRefreshHourEt
    property int    eodRefreshMinuteEt: plasmoid.configuration.eodRefreshMinuteEt
    // Intraday SPX-only refresh cadence (minutes). GEX/flip stay EOD-fixed.
    property int    spotRefreshIntervalMinutes: Math.max(1, plasmoid.configuration.spotRefreshIntervalMinutes)
    // ET date-key (YYYY-M-D) of the last completed daily fetch; guards re-fetch.
    property string lastEodFetchDate:   ""
    readonly property string eodRefreshLabel:
        (root.eodRefreshHourEt < 10 ? "0" : "") + root.eodRefreshHourEt + ":"
        + (root.eodRefreshMinuteEt < 10 ? "0" : "") + root.eodRefreshMinuteEt + " ET"

    // ── Helpers ──────────────────────────────────────────────────────────────
    readonly property color regimeColor: {
        if (!root.hasData || root.regime.length === 0) return Kirigami.Theme.disabledTextColor
        return root.regime === "positive"
            ? Kirigami.Theme.positiveTextColor
            : Kirigami.Theme.negativeTextColor
    }
    readonly property string regimeGlyph: {
        if (!root.hasData || root.regime.length === 0) return "—"
        return root.regime === "positive" ? "▲" : "▼"
    }
    readonly property string spotText:   root.hasData && !isNaN(root.spot) ? root.spot.toFixed(1) : "—"
    readonly property string gexText: {
        if (!root.hasData || isNaN(root.netGex)) return "—"
        return (root.netGex >= 0 ? "+" : "") + root.netGex.toFixed(2)
    }
    readonly property string flipText:   root.hasData && !isNaN(root.flip) ? Math.round(root.flip).toString() : "—"
    readonly property string flipDeltaText: {
        if (!root.hasData || isNaN(root.flipDistance)) return "—"
        var d  = (root.flipDistance >= 0 ? "+" : "") + Math.round(root.flipDistance)
        var dp = (root.flipDistancePct >= 0 ? "+" : "") + root.flipDistancePct.toFixed(2)
        return d + " (" + dp + "%)"
    }
    // "6250 (+85)" — strike plus signed distance to spot.
    function wallText(strike, distance) {
        if (!root.hasData || isNaN(strike)) return "—"
        var s = Math.round(strike).toString()
        if (isNaN(distance)) return s
        return s + " (" + (distance >= 0 ? "+" : "") + Math.round(distance) + ")"
    }
    readonly property string iv30Text: {
        if (!root.hasData || isNaN(root.iv30)) return "—"
        var t = root.iv30.toFixed(2)
        if (!isNaN(root.iv30ChangePct)) {
            t += "  (" + (root.iv30ChangePct >= 0 ? "+" : "") + root.iv30ChangePct.toFixed(1) + "%)"
        }
        return t
    }
    readonly property color iv30Color: {
        if (!root.hasData || isNaN(root.iv30ChangePct)) return Kirigami.Theme.textColor
        // Rising IV = richer premium for a seller, so it is not "bad" -- keep it
        // neutral-informative rather than borrowing the P&L colour scheme.
        return Kirigami.Theme.textColor
    }
    // Data age in minutes -> "18 min" / "3.2 h" / "2 d".
    readonly property string dataAgeText: {
        if (isNaN(root.dataAgeMin)) return ""
        var m = root.dataAgeMin
        if (m < 90) return Math.round(m) + " min"
        if (m < 60 * 36) return (m / 60).toFixed(1) + " h"
        return Math.round(m / 1440) + " d"
    }
    // CBOE is ~15 min delayed by design; flag only clearly stale data.
    readonly property bool dataIsStale: !isNaN(root.dataAgeMin) && root.dataAgeMin > 45

    readonly property string callWallText: root.wallText(root.callWall, root.callWallDistance)
    readonly property string putWallText:  root.wallText(root.putWall,  root.putWallDistance)

    // ── Compact representation (panel) ──────────────────────────────────────
    compactRepresentation: Item {
        implicitWidth:  Math.round(Kirigami.Units.gridUnit * 2.8)
        implicitHeight: Math.round(Kirigami.Units.gridUnit * 2)

        MouseArea {
            anchors.fill: parent
            onClicked: plasmoid.expanded = !plasmoid.expanded
        }

        // mode 0: SPX price + regime color, flip-distance subtext
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 0
            visible: plasmoid.configuration.compactMode === 0

            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.spotText
                font.pointSize: Kirigami.Units.gridUnit * 0.85
                color: root.status === "error" ? Kirigami.Theme.negativeTextColor : root.regimeColor
            }
            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.hasData && !isNaN(root.flipDistance)
                    ? "flip " + (root.flipDistance >= 0 ? "+" : "") + Math.round(root.flipDistance)
                    : "SPX"
                font.pointSize: Kirigami.Units.gridUnit * 0.5
                color: Kirigami.Theme.disabledTextColor
            }
        }

        // mode 1: Net GEX value (colored by sign) + SPX price subtext
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 0
            visible: plasmoid.configuration.compactMode === 1

            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.gexText
                font.pointSize: Kirigami.Units.gridUnit * 0.8
                color: root.status === "error" ? Kirigami.Theme.negativeTextColor : root.regimeColor
            }
            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.spotText
                font.pointSize: Kirigami.Units.gridUnit * 0.55
                color: Kirigami.Theme.disabledTextColor
            }
        }

        // mode 2: regime glyph + price below
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 0
            visible: plasmoid.configuration.compactMode === 2

            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.regimeGlyph
                font.pointSize: Kirigami.Units.gridUnit * 0.95
                color: root.status === "error" ? Kirigami.Theme.negativeTextColor : root.regimeColor
            }
            PlasmaComponents3.Label {
                Layout.alignment: Qt.AlignHCenter
                text: root.spotText
                font.pointSize: Kirigami.Units.gridUnit * 0.6
                color: Kirigami.Theme.disabledTextColor
            }
        }
    }

    // ── Full representation (numbers only) ───────────────────────────────────
    fullRepresentation: Item {
        Layout.minimumWidth:    Kirigami.Units.gridUnit * 14
        Layout.minimumHeight:   Kirigami.Units.gridUnit * 14
        Layout.preferredWidth:  Kirigami.Units.gridUnit * 16
        Layout.preferredHeight: Kirigami.Units.gridUnit * 16

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing * 2
            spacing: Kirigami.Units.smallSpacing

            // Header
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Label {
                    text: i18n("SPX Dealer Gamma")
                    font.bold: true
                    Layout.fillWidth: true
                }

                PlasmaComponents3.ToolButton {
                    icon.name: "view-refresh"
                    enabled: !root.isRefreshing
                    onClicked: root.fetchData()
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.text: i18n("Refresh data")
                }
            }

            // Error message
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: root.status === "error" && root.errorMessage.length > 0
                text: root.errorMessage
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.WordWrap
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }

            // Metric rows
            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                columns: 2
                rowSpacing: Kirigami.Units.smallSpacing
                columnSpacing: Kirigami.Units.gridUnit

                // SPX
                PlasmaComponents3.Label {
                    text: i18n("SPX")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.spotText
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.3
                }

                // Net GEX
                PlasmaComponents3.Label {
                    text: i18n("Net GEX")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.hasData && !isNaN(root.netGex)
                        ? i18n("%1 Bn$/1%", root.gexText)
                        : "—"
                    font.bold: true
                    color: root.regimeColor
                }

                // Regime
                PlasmaComponents3.Label {
                    text: i18n("Regime")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: {
                        if (!root.hasData || root.regime.length === 0) return "—"
                        return root.regime === "positive"
                            ? i18n("POSITIVE")
                            : i18n("NEGATIVE")
                    }
                    color: root.regimeColor
                }

                // IV30 (CBOE 30-day implied vol, ships with every quote)
                PlasmaComponents3.Label {
                    text: i18n("IV30")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.iv30Text
                    color: root.iv30Color
                }

                // Flip level
                PlasmaComponents3.Label {
                    text: i18n("Gamma Flip")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.flipText
                    font.bold: true
                }

                // Distance
                PlasmaComponents3.Label {
                    text: i18n("Δ to Spot")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.flipDeltaText
                    color: Kirigami.Theme.disabledTextColor
                }

                // Call Wall
                PlasmaComponents3.Label {
                    text: i18n("Call Wall")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.callWallText
                    font.bold: true
                    color: root.hasData && !isNaN(root.callWall)
                        ? Kirigami.Theme.positiveTextColor
                        : Kirigami.Theme.disabledTextColor
                }

                // Put Wall
                PlasmaComponents3.Label {
                    text: i18n("Put Wall")
                    color: Kirigami.Theme.disabledTextColor
                }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignRight
                    text: root.putWallText
                    font.bold: true
                    color: root.hasData && !isNaN(root.putWall)
                        ? Kirigami.Theme.negativeTextColor
                        : Kirigami.Theme.disabledTextColor
                }
            }

            Item { Layout.fillHeight: true }

            // Status bar
            StatusBar {
                Layout.fillWidth: true
                status: root.status
                lastSuccessfulUpdate: root.lastSuccessfulUpdate
                regime: root.regime
                refreshLabel: root.eodRefreshLabel
                dataAgeText: root.dataAgeText
                dataIsStale: root.dataIsStale
            }
        }
    }

    // ── Data source ──────────────────────────────────────────────────────────
    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []

        onNewData: function(sourceName, data) {
            executable.disconnectSource(sourceName)
            var stdout   = data["stdout"]   || ""
            var stderr   = data["stderr"]   || ""
            var exitCode = data["exit code"] !== undefined ? data["exit code"] : -1
            handleFetcherOutput(stdout, stderr, exitCode)
        }
    }

    // ── Timers ───────────────────────────────────────────────────────────────
    // Data is EOD (Open Interest publishes once/day), so instead of polling we
    // tick once a minute and fire a single fetch once per weekday after the
    // configured ET refresh time. DST-safe: ET wall-clock is read each tick.
    Timer {
        id: refreshTimer
        interval: 60 * 1000
        repeat: true
        running: root.visible
        onTriggered: root.maybeEodRefresh()
    }

    // Intraday SPX price poll. Fetches spot only (not GEX/flip), gated on US
    // market hours so off-hours/weekends don't fire wasted requests.
    Timer {
        id: spotTimer
        interval: root.spotRefreshIntervalMinutes * 60 * 1000
        repeat: true
        running: root.visible
        onTriggered: root.maybeSpotRefresh()
    }

    Timer {
        id: fetchTimeout
        interval: 30000
        repeat: false
        onTriggered: {
            root.isRefreshing = false
            root.status = "error"
            root.errorMessage = i18n("Fetcher did not respond within 30s. Check that python3, requests, numpy, pandas and scipy are installed.")
        }
    }

    // ── Config reactivity ────────────────────────────────────────────────────
    Connections {
        target: plasmoid.configuration
        function onEodRefreshHourEtChanged() {
            root.eodRefreshHourEt = plasmoid.configuration.eodRefreshHourEt
        }
        function onEodRefreshMinuteEtChanged() {
            root.eodRefreshMinuteEt = plasmoid.configuration.eodRefreshMinuteEt
        }
        function onSpotRefreshIntervalMinutesChanged() {
            root.spotRefreshIntervalMinutes = Math.max(1, plasmoid.configuration.spotRefreshIntervalMinutes)
            spotTimer.interval = root.spotRefreshIntervalMinutes * 60 * 1000
            spotTimer.restart()
        }
        function onMaxDteChanged() {
            root.fetchData()
        }
        // Wall window only reshuffles strikes -- the cached chain is enough.
        function onWallMinDteChanged() {
            root.fetchIntraday()
        }
    }

    // ── Lifecycle ────────────────────────────────────────────────────────────
    Component.onCompleted: {
        // Restart/login: recompute from the cached chain instead of pulling the
        // full chain again. The fetcher downloads it only if no cache is there.
        fetchIntraday()
        // If we start up after today's refresh time, mark today done so the
        // ticker doesn't immediately fire a duplicate fetch.
        var et = root.etNow()
        if (root.etMinutesPastRefresh(et) && !root.isEtWeekend(et)) {
            root.lastEodFetchDate = root.etDateKey(et)
        }
        refreshTimer.start()
        spotTimer.start()
    }

    onExpandedChanged: {
        if (plasmoid.expanded) {
            // GEX and flip only move with the daily OI snapshot, so opening the
            // popup just refreshes the price via the light quote endpoint. The
            // refresh button still forces a full reload.
            // Intraday recompute is cheap and self-heals into a full fetch when
            // the chain cache is missing, so it is the right call either way.
            fetchIntraday()
        }
    }

    // ── Functions ────────────────────────────────────────────────────────────
    function quoteShell(value) {
        return "'" + String(value).replace(/'/g, "'\\''") + "'"
    }

    // ── EOD scheduling helpers (US Eastern, DST-safe) ────────────────────────
    // Date whose local getters reflect ET wall-clock (reparse of the ET-localized
    // string). Good enough for hour/minute/day-of-week comparisons.
    function etNow() {
        return new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }))
    }
    function etDateKey(et) {
        return et.getFullYear() + "-" + (et.getMonth() + 1) + "-" + et.getDate()
    }
    function isEtWeekend(et) {
        var d = et.getDay()   // 0 = Sun, 6 = Sat — no new EOD data
        return d === 0 || d === 6
    }
    function etMinutesPastRefresh(et) {
        var nowMin    = et.getHours() * 60 + et.getMinutes()
        var targetMin = root.eodRefreshHourEt * 60 + root.eodRefreshMinuteEt
        return nowMin >= targetMin
    }
    // US regular session 09:30–16:00 ET. etNow() is DST-safe and independent of
    // the machine's local timezone (reparses via America/New_York), so this is
    // correct whether the user is on CET, UTC, etc.
    function isEtMarketHours(et) {
        var m = et.getHours() * 60 + et.getMinutes()
        return m >= (9 * 60 + 30) && m <= (16 * 60)
    }
    // Intraday: refresh SPX price only, during market hours on weekdays.
    function maybeSpotRefresh() {
        var et = root.etNow()
        if (root.isEtWeekend(et)) return
        if (!root.isEtMarketHours(et)) return
        root.fetchIntraday()
    }
    // Fire one fetch per weekday once we're past the configured ET time.
    function maybeEodRefresh() {
        var et = root.etNow()
        if (root.isEtWeekend(et)) return
        var key = root.etDateKey(et)
        if (root.lastEodFetchDate === key) return
        if (!root.etMinutesPastRefresh(et)) return
        root.lastEodFetchDate = key
        fetchData()
    }

    function fetchData() {
        if (root.isRefreshing) {
            return
        }
        root.isRefreshing = true
        root.status = root.hasData ? "refreshing" : "loading"
        fetchTimeout.stop()

        var scriptUrl = Qt.resolvedUrl("../code/fetch_gamma.py")
        var script    = scriptUrl.toString().replace(/^file:\/\//, "")
        var command   = "python3 " + quoteShell(script)
                      + " --mode full"
                      + root.commonArgs()
        executable.connectSource(command)
        fetchTimeout.start()
    }

    // Arguments shared by the full and the intraday run, so both windows the
    // chain identically -- otherwise the intraday recompute would silently
    // disagree with the EOD numbers it replaces.
    function commonArgs() {
        return " --max-dte " + Math.max(1, plasmoid.configuration.maxDte)
             + " --wall-min-dte " + Math.max(0, plasmoid.configuration.wallMinDte)
             + " --timeout 12"
    }

    // Intraday refresh: pulls the ~540 byte CBOE index quote and recomputes
    // GEX, regime, flip and walls from the cached chain at the live spot and
    // with freshly decayed time to expiry. No chain download. Open interest
    // stays EOD -- everything that does move during the session now follows.
    // Falls back to a full fetch inside the fetcher when no cache exists.
    // Shares isRefreshing so it won't collide with a full fetch in flight.
    function fetchIntraday() {
        if (root.isRefreshing) {
            return
        }
        root.isRefreshing = true
        fetchTimeout.stop()

        var scriptUrl = Qt.resolvedUrl("../code/fetch_gamma.py")
        var script    = scriptUrl.toString().replace(/^file:\/\//, "")
        var command   = "python3 " + quoteShell(script)
                      + " --mode intraday"
                      + root.commonArgs()
        executable.connectSource(command)
        fetchTimeout.start()
    }

    function handleFetcherOutput(stdout, stderr, exitCode) {
        root.isRefreshing = false
        fetchTimeout.stop()

        if (!stdout || stdout.trim().length === 0) {
            root.status       = "error"
            root.errorMessage = stderr && stderr.length > 0
                ? stderr
                : i18n("Fetcher returned no JSON output")
            return
        }

        try {
            var result = JSON.parse(stdout)

            // Quote-only response (fallback when the chain cache is missing):
            // price and IV30 only, gamma numbers keep their last values and the
            // flip/wall distances are re-derived against the new spot.
            if (result.status === "ok" && result.mode === "spot") {
                root.applyMeta(result)
                if (result.spot !== null && result.spot !== undefined) {
                    root.spot    = result.spot
                    root.hasData = true
                    if (!isNaN(root.flip)) {
                        root.flipDistance    = root.flip - root.spot
                        root.flipDistancePct = (root.flip / root.spot - 1.0) * 100.0
                    }
                    if (!isNaN(root.callWall)) {
                        root.callWallDistance = root.callWall - root.spot
                    }
                    if (!isNaN(root.putWall)) {
                        root.putWallDistance = root.putWall - root.spot
                    }
                    root.lastUpdate           = result.timestamp || ""
                    root.lastSuccessfulUpdate = root.lastUpdate
                    root.status               = "ok"
                }
                return   // no chain available -> netGex / regime / flip unchanged
            }

            if (result.status === "ok" || result.status === "partial") {
                root.spot            = (result.spot !== null && result.spot !== undefined) ? result.spot : NaN
                root.netGex          = (result.net_gex !== null && result.net_gex !== undefined) ? result.net_gex : NaN
                root.regime          = result.regime || ""
                root.flip            = (result.flip !== null && result.flip !== undefined) ? result.flip : NaN
                root.flipDistance    = (result.flip_distance !== null && result.flip_distance !== undefined) ? result.flip_distance : NaN
                root.flipDistancePct = (result.flip_distance_pct !== null && result.flip_distance_pct !== undefined) ? result.flip_distance_pct : NaN

                root.callWall         = root.numOrNaN(result.call_wall)
                root.callWallGex      = root.numOrNaN(result.call_wall_gex)
                root.callWallDistance = root.numOrNaN(result.call_wall_distance)
                root.putWall          = root.numOrNaN(result.put_wall)
                root.putWallGex       = root.numOrNaN(result.put_wall_gex)
                root.putWallDistance  = root.numOrNaN(result.put_wall_distance)

                root.applyMeta(result)
                root.lastUpdate = result.timestamp || ""
                root.hasData    = !isNaN(root.spot)
                if (root.hasData) {
                    root.lastSuccessfulUpdate = root.lastUpdate
                }

                root.status       = result.status
                root.errorMessage = formatErrors(result.errors || [])
                return
            }

            root.status       = "error"
            root.errorMessage = formatErrors(result.errors || [])
                || i18n("Could not fetch data")
        } catch (e) {
            root.status       = "error"
            root.errorMessage = i18n("Could not parse fetcher JSON: %1", e)
        }
    }

    // IV30 and the data-age fields ride along in every response, including the
    // quote-only one, so they are applied separately from the gamma block.
    function applyMeta(result) {
        root.iv30          = root.numOrNaN(result.iv30)
        root.iv30ChangePct = root.numOrNaN(result.iv30_change_pct)
        root.dataAgeMin    = root.numOrNaN(result.data_age_min)
        root.chainAgeHours = root.numOrNaN(result.chain_age_hours)
        root.dataMode      = result.mode || ""
    }

    // JSON nulls (a wall side can be empty) map to NaN, which the "—" texts key off.
    function numOrNaN(value) {
        return (value !== null && value !== undefined) ? Number(value) : NaN
    }

    function formatErrors(errors) {
        if (!errors || errors.length === 0) return ""
        return errors.map(function(e) {
            return e.message ? e.message : String(e)
        }).join(", ")
    }
}

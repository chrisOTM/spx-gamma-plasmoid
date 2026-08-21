import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_eodRefreshHourEt: eodHour.value
    property alias cfg_eodRefreshMinuteEt: eodMinute.value
    property alias cfg_spotRefreshIntervalMinutes: spotInterval.value
    property int   cfg_compactMode: 0
    property alias cfg_maxDte: maxDte.value
    property alias cfg_wallMinDte: wallMinDte.value

    // SPX option data (Open Interest) is published once per day, so the
    // widget fetches a single EOD snapshot after the US market close.
    RowLayout {
        Kirigami.FormData.label: i18n("Daily EOD refresh (US Eastern):")

        QQC2.SpinBox {
            id: eodHour
            from: 0
            to: 23
            value: 16
            textFromValue: function(v) { return (v < 10 ? "0" : "") + v }
        }
        QQC2.Label { text: ":" }
        QQC2.SpinBox {
            id: eodMinute
            from: 0
            to: 59
            value: 30
            stepSize: 5
            textFromValue: function(v) { return (v < 10 ? "0" : "") + v }
        }
        QQC2.Label {
            text: i18n("ET")
            color: Kirigami.Theme.disabledTextColor
        }
    }

    // SPX spot moves intraday — refresh just the price (not GEX/flip) every N
    // minutes, but only during US regular trading hours.
    QQC2.SpinBox {
        id: spotInterval
        Kirigami.FormData.label: i18n("Intraday SPX price refresh (minutes):")
        from: 1
        to: 240
        value: 15
    }
    QQC2.Label {
        text: i18n("Polls only during US market hours (09:30–16:00 ET).")
        font: Kirigami.Theme.smallFont
        color: Kirigami.Theme.disabledTextColor
    }

    QQC2.ComboBox {
        id: compactMode
        Kirigami.FormData.label: i18n("Panel display:")
        model: [
            i18n("SPX price + regime color"),
            i18n("Net GEX value"),
            i18n("Regime glyph + price")
        ]
        currentIndex: page.cfg_compactMode
        onActivated: page.cfg_compactMode = currentIndex
    }

    Item {
        Kirigami.FormData.isSection: true
    }

    QQC2.SpinBox {
        id: maxDte
        Kirigami.FormData.label: i18n("Max days to expiry:")
        from: 1
        to: 730
        value: 90
    }

    // Same-day expiries carry open interest that is gone by the close; a wall
    // is meant to be a level that survives the session.
    QQC2.SpinBox {
        id: wallMinDte
        Kirigami.FormData.label: i18n("Wall minimum days to expiry:")
        from: 0
        to: 60
        value: 1
    }
    QQC2.Label {
        text: i18n("0 includes today's expiry in the put/call walls.")
        font: Kirigami.Theme.smallFont
        color: Kirigami.Theme.disabledTextColor
    }
}

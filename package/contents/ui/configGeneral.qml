import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_refreshIntervalMinutes: refreshInterval.value
    property int   cfg_compactMode: 0
    property alias cfg_maxDte: maxDte.value

    QQC2.SpinBox {
        id: refreshInterval
        Kirigami.FormData.label: i18n("Refresh interval in minutes:")
        from: 1
        to: 1440
        value: 15
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
}

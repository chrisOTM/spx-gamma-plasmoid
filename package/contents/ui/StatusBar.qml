import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: statusBar

    property string status: "loading"
    property string lastSuccessfulUpdate: ""
    property string regime: ""
    property string refreshLabel: ""

    spacing: Kirigami.Units.smallSpacing * 2

    // ISO timestamp -> "11 Jun 10:10" (locale month). Falls back to raw on parse fail.
    function formatTimestamp(iso) {
        if (!iso || iso.length === 0) return ""
        var d = new Date(iso)
        if (isNaN(d.getTime())) return iso
        return Qt.formatDateTime(d, "dd MMM HH:mm")
    }

    PlasmaComponents3.Label {
        id: statusLabel
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: {
            switch (statusBar.status) {
                case "ok":         return Kirigami.Theme.positiveTextColor
                case "partial":    return Kirigami.Theme.neutralTextColor
                case "error":      return Kirigami.Theme.negativeTextColor
                default:           return Kirigami.Theme.disabledTextColor
            }
        }
        text: {
            switch (statusBar.status) {
                case "ok":         return i18n("OK")
                case "partial":    return i18n("Partial")
                case "error":      return i18n("Error")
                case "loading":    return i18n("Loading…")
                case "refreshing": return i18n("Refreshing…")
                default:           return i18n("Unknown")
            }
        }
    }

    PlasmaComponents3.Label {
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: Kirigami.Theme.disabledTextColor
        text: "|"
    }

    PlasmaComponents3.Label {
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: Kirigami.Theme.disabledTextColor
        text: statusBar.lastSuccessfulUpdate.length > 0
            ? statusBar.formatTimestamp(statusBar.lastSuccessfulUpdate)
            : i18n("No data yet")
        elide: Text.ElideRight
        Layout.fillWidth: true
    }

    PlasmaComponents3.Label {
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: Kirigami.Theme.disabledTextColor
        text: "|"
    }

    PlasmaComponents3.Label {
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: Kirigami.Theme.disabledTextColor
        text: statusBar.refreshLabel
        visible: statusBar.refreshLabel.length > 0
    }
}

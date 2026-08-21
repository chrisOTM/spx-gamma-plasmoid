import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: statusBar

    property string status: "loading"
    property string lastSuccessfulUpdate: ""
    property string regime: ""
    property string refreshLabel: ""
    // Age of the data itself (last index print), not of the fetch. A fetch on a
    // holiday returns a fresh clock on stale numbers, so the fetch time alone
    // cannot tell a trader whether what is on screen is current.
    property string dataAgeText: ""
    property bool   dataIsStale: false

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

    // Data age is the headline, the fetch clock only the tooltip.
    PlasmaComponents3.Label {
        id: ageLabel
        readonly property string fetchText:
            statusBar.lastSuccessfulUpdate.length > 0
                ? statusBar.formatTimestamp(statusBar.lastSuccessfulUpdate)
                : ""
        font.pointSize: Kirigami.Theme.smallFont.pointSize
        color: statusBar.dataIsStale
            ? Kirigami.Theme.neutralTextColor
            : Kirigami.Theme.disabledTextColor
        text: {
            if (statusBar.dataAgeText.length > 0)
                return i18n("data %1", statusBar.dataAgeText)
            if (ageLabel.fetchText.length > 0) return ageLabel.fetchText
            return i18n("No data yet")
        }
        elide: Text.ElideRight
        Layout.fillWidth: true

        HoverHandler { id: ageHover }
        QQC2.ToolTip.visible: ageHover.hovered && ageLabel.fetchText.length > 0
        QQC2.ToolTip.text: i18n("Last fetch: %1", ageLabel.fetchText)
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

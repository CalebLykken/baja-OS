import QtQuick
import QtQuick.Layouts

// The next turn over the top of Home's map, on the same dark card as the Maps page.
// During a reroute the old turn no longer exists, so it shows what the nav rail's
// TurnChip shows: the refresh icon and "Rerouting", until the new route lands.
Rectangle {
    id: card
    readonly property bool shown: typeof routing !== "undefined" && routing.active
    readonly property bool rerouting: shown && routing.computing
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    transform: Translate {
        y: card.shown ? 0 : -16
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }
    height: miniTurn.implicitHeight + 28
    radius: Theme.radius
    color: Theme.base.panel
    RowLayout {
        id: miniTurn
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
        spacing: 12
        Icon {
            objectName: "homeTurnIcon"
            Layout.alignment: Qt.AlignTop
            name: card.rerouting ? "refresh"
                  : typeof routing !== "undefined" ? routing.maneuverIcon || "straight" : "straight"
            size: 64
            color: Theme.base.text
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Label {
                objectName: "homeTurnDistance"
                Layout.fillWidth: true
                visible: card.rerouting || (typeof routing !== "undefined" && !routing.arrived)
                numeric: true
                elide: Text.ElideRight
                text: card.rerouting ? "Rerouting"
                      : typeof routing !== "undefined" ? Units.distanceText(routing.distanceToTurn) : ""
                color: Theme.base.text
                font.pixelSize: Theme.fontReadout
            }
            Label {
                objectName: "homeTurnText"
                Layout.fillWidth: true
                // Faded, not hidden, so the card keeps its size through a reroute.
                opacity: card.rerouting ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                text: typeof routing !== "undefined" ? routing.instruction : ""
                color: Theme.base.text
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
            }
        }
    }
}

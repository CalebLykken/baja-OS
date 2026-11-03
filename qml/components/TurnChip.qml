import QtQuick

// The next turn while a route is being driven, at the foot of the nav rail
// on the pages that don't show the map. Tap for Maps.
Rectangle {
    id: chip
    signal tapped()

    readonly property bool active: typeof routing !== "undefined" && routing.active

    width: 96
    height: column.implicitHeight + 16
    radius: Theme.radius
    color: tap.pressed ? Theme.panelHi : Theme.panel
    border.width: Theme.border
    border.color: Theme.accent
    opacity: active ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Column {
        id: column
        anchors.centerIn: parent
        spacing: 2
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: chip.active ? routing.maneuverIcon || "straight" : "straight"
            size: 36
            color: Theme.accent
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            numeric: true
            font.pixelSize: Theme.fontSmall
            font.weight: Font.DemiBold
            text: !chip.active ? "" : routing.arrived ? "Here" : Units.distanceText(routing.distanceToTurn)
        }
    }

    TapHandler { id: tap; onTapped: chip.tapped() }
}

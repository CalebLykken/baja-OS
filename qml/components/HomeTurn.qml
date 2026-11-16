import QtQuick
import QtQuick.Layouts

// The next turn over the top of Home's map, on the same dark card as the Maps page.
// During a reroute the old turn no longer exists, so it shows what the nav rail's
// TurnChip shows: the refresh icon and "Rerouting", until the new route lands.
Rectangle {
    id: card
    readonly property bool shown: typeof routing !== "undefined" && routing.active
    readonly property bool rerouting: shown && routing.computing
    // The turn after this one, shown small beside the distance when there is one.
    readonly property bool thenShown: typeof routing !== "undefined" && routing.thenIcon !== ""
                                      && !routing.computing && !routing.arrived
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
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                visible: card.rerouting || (typeof routing !== "undefined" && !routing.arrived)
                Label {
                    objectName: "homeTurnDistance"
                    Layout.fillWidth: true
                    numeric: true
                    // Shrinks rather than pushing the "Then" group off the card.
                    fontSizeMode: Text.Fit
                    minimumPixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                    text: card.rerouting ? "Rerouting"
                          : typeof routing !== "undefined" ? Units.distanceText(routing.distanceToTurn) : ""
                    color: Theme.base.text
                    font.pixelSize: Theme.fontReadout
                }
                // The turn after this one, for a quick lane change on a short block.
                RowLayout {
                    objectName: "homeTurnThen"
                    Layout.alignment: Qt.AlignRight | Qt.AlignBottom
                    spacing: 4
                    visible: card.thenShown
                    Label {
                        text: "Then"
                        color: Theme.base.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                    Icon {
                        objectName: "homeTurnThenIcon"
                        name: typeof routing !== "undefined" ? routing.thenIcon : ""
                        size: 40
                        color: Theme.base.textDim
                    }
                }
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

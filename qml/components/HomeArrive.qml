import QtQuick
import QtQuick.Layouts

// The arrival pill over the bottom-left of Home's map: the clock time you get
// there in bold, then "24 min · 12 mi" dimmer. Once you have arrived there is
// nothing left to count down, so it shows the arrival summary ("14 min · right
// on time") if there is one and hides otherwise.
Rectangle {
    id: pill
    readonly property bool hasRouting: typeof routing !== "undefined"
    readonly property string summary: hasRouting && routing.arrived ? routing.arrivalSummary : ""
    readonly property bool shown: hasRouting && routing.active && (!routing.arrived || summary !== "")
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    transform: Translate {
        y: pill.shown ? 0 : 16
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }
    // The map tile is narrow, so a long distance elides rather than overflows.
    readonly property real maximumWidth: parent ? parent.width - 24 : 400
    width: Math.min(row.implicitWidth + 32, maximumWidth)
    height: 64
    radius: Theme.radius
    color: Theme.panel
    border.width: Theme.border
    border.color: Theme.line
    RowLayout {
        id: row
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 16 }
        spacing: 12
        Label {
            objectName: "arriveEta"
            visible: pill.summary === ""
            numeric: true
            text: pill.hasRouting && !routing.arrived ? Units.arrivalText(routing.remainingTime) : ""
            color: Theme.text
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
        }
        Label {
            objectName: "arriveRest"
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: !pill.hasRouting ? ""
                  : pill.summary !== "" ? pill.summary
                  : routing.arrived ? ""
                  : Units.durationText(routing.remainingTime) + " · " + Units.distanceText(routing.remainingDistance)
            color: pill.summary !== "" ? Theme.text : Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
    }
}

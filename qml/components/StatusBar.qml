import QtQuick

// Top strip: current screen, clock, and the two numbers worth always seeing.
Item {
    id: bar
    property string title
    height: 64

    Label {
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        text: bar.title
        color: Theme.text
        font.pixelSize: Theme.fontTitle
        font.weight: Font.DemiBold
    }

    Label {
        id: clock
        anchors.centerIn: parent
        color: Theme.text
        font.pixelSize: Theme.fontTitle
        text: Qt.formatTime(new Date(), "h:mm")
        Timer {
            interval: 5000; running: true; repeat: true
            onTriggered: clock.text = Qt.formatTime(new Date(), "h:mm")
        }
    }

    Row {
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        spacing: 24

        Rectangle {
            visible: typeof demoMode !== "undefined" && demoMode
            anchors.verticalCenter: parent.verticalCenter
            width: demoText.width + 20; height: 30; radius: Theme.radius
            color: Theme.accentDim
            Legend {
                id: demoText
                anchors.centerIn: parent
                text: "Demo data"
                color: Theme.accent
                font.letterSpacing: 1.5
            }
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: Math.round(vehicle.coolant) + "°F"
            color: vehicle.coolant > 230 ? Theme.warn : Theme.textDim
            font.pixelSize: Theme.fontBody
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: vehicle.voltage.toFixed(1) + " V"
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
    }
}

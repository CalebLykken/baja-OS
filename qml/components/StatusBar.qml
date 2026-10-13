import QtQuick

// Top strip: current screen, clock, and the two numbers worth always seeing.
Item {
    id: bar
    property string title
    height: 64

    Text {
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        text: bar.title
        color: Theme.text
        font.pixelSize: Theme.fontTitle
        font.weight: Font.DemiBold
    }

    Text {
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
            width: demoText.width + 20; height: 28; radius: 14
            color: Theme.accentDim
            Text {
                id: demoText
                anchors.centerIn: parent
                text: "DEMO DATA"
                color: Theme.accent
                font.pixelSize: 12
                font.letterSpacing: 1.5
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: Math.round(vehicle.coolant) + "°F"
            color: vehicle.coolant > 230 ? Theme.warn : Theme.textDim
            font.pixelSize: Theme.fontBody
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: vehicle.voltage.toFixed(1) + " V"
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
    }
}

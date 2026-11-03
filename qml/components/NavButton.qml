import QtQuick

// One entry in the left-hand navigation rail.
Item {
    id: btn
    property string icon
    property string label
    property bool active: false
    signal clicked()

    width: parent ? parent.width : 112
    height: 96

    Rectangle {
        anchors { fill: parent; margins: 8 }
        radius: Theme.radius
        color: btn.active ? Theme.panelHi : (tap.pressed ? Theme.panel : "transparent")
        Behavior on color { ColorAnimation { duration: 150 } }
        scale: tap.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: 70 } }

        Rectangle {
            visible: btn.active
            width: 4
            height: parent.height * 0.5
            radius: 2
            color: Theme.accent
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        }

        Column {
            anchors.centerIn: parent
            spacing: 6
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: btn.icon
                size: 34
                color: btn.active ? Theme.accent : Theme.textDim
                Behavior on color { ColorAnimation { duration: 150 } }
            }
            Legend {
                anchors.horizontalCenter: parent.horizontalCenter
                text: btn.label
                font.letterSpacing: 1        // tighter so SETTINGS fits the rail
                color: btn.active ? Theme.text : Theme.textDim
                Behavior on color { ColorAnimation { duration: 150 } }
            }
        }
    }

    TapHandler {
        id: tap
        onTapped: btn.clicked()
    }
}

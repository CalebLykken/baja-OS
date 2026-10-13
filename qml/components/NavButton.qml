import QtQuick

// One entry in the left-hand navigation rail.
Item {
    id: btn
    property string glyph
    property string label
    property bool active: false
    signal clicked()

    width: parent ? parent.width : 112
    height: 104

    Rectangle {
        anchors { fill: parent; margins: 8 }
        radius: Theme.radius
        color: btn.active ? Theme.panelHi : (tap.pressed ? Theme.panel : "transparent")

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
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: btn.glyph
                font.pixelSize: 32
                color: btn.active ? Theme.accent : Theme.textDim
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: btn.label.toUpperCase()
                font.pixelSize: 13
                font.letterSpacing: 1.5
                color: btn.active ? Theme.text : Theme.textDim
            }
        }
    }

    TapHandler {
        id: tap
        onTapped: btn.clicked()
    }
}

import QtQuick

// Rounded panel used for every tile. Set `tappable` to get press feedback
// and a `tapped` signal.
Rectangle {
    id: card
    property bool tappable: false
    property string heading: ""
    signal tapped()

    color: tappable && tap.pressed ? Theme.panelHi : Theme.panel
    radius: Theme.radius
    border.color: Theme.line
    border.width: 1

    Text {
        visible: card.heading !== ""
        text: card.heading.toUpperCase()
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall - 2
        font.letterSpacing: 2
        anchors { left: parent.left; top: parent.top; leftMargin: 20; topMargin: 16 }
    }

    TapHandler {
        id: tap
        enabled: card.tappable
        onTapped: card.tapped()
    }
}

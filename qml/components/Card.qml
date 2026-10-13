import QtQuick

// Rounded panel used for every tile. Set `tappable` to get press feedback
// and a `tapped` signal.
Rectangle {
    id: card
    property bool tappable: false
    property string heading: ""
    signal tapped()

    radius: Theme.radius
    border.color: Theme.line
    border.width: Theme.border
    gradient: Gradient {
        GradientStop { position: 0; color: card.tappable && tap.pressed ? Theme.panelHi : Theme.panelTop }
        GradientStop { position: 1; color: card.tappable && tap.pressed ? Theme.panelHi : Theme.panel }
    }

    Label {
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

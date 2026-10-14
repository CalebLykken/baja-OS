import QtQuick

// Rounded panel used for every tile. Set `tappable` to get press feedback
// and a `tapped` signal.
Rectangle {
    id: card
    property bool tappable: false
    property string heading: ""
    // 0 = solid panel; up to 1 = see-through, for cards over a backdrop
    // (the Music page's blurred album art).
    property real glass: 0
    signal tapped()

    function fill(c) { return Qt.rgba(c.r, c.g, c.b, 1 - glass) }

    radius: Theme.radius
    border.color: Theme.line
    border.width: Theme.border
    gradient: Gradient {
        GradientStop { position: 0; color: card.fill(card.tappable && tap.pressed ? Theme.panelHi : Theme.panelTop) }
        GradientStop { position: 1; color: card.fill(card.tappable && tap.pressed ? Theme.panelHi : Theme.panel) }
    }
    Behavior on glass { NumberAnimation { duration: 400 } }

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

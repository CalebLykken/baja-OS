import QtQuick

// The panel every tile sits on: solid, with the style's border and radius.
// `heading` is an optional sentence-case caption for cards whose content
// needs one ("Up next on Spotify"). Set `tappable` for press feedback and a
// `tapped` signal.
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
        text: card.heading
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        font.weight: Font.DemiBold
        anchors { left: parent.left; top: parent.top; leftMargin: 20; topMargin: 16 }
    }

    TapHandler {
        id: tap
        enabled: card.tappable
        onTapped: card.tapped()
    }
}

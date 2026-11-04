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
    scale: card.tappable && tap.pressed ? 0.97 : 1
    // Press dips in 70 ms, release springs back in 180 ms (OutBack). The same
    // numbers are used in Card, TextButton, IconButton, NavButton, Keyboard and
    // SegmentedControl. Runs only on a touch, so there is no idle cost.
    Behavior on scale { id: pressSpring; enabled: card.tappable; NumberAnimation { duration: pressSpring.targetValue < 1 ? 70 : 180; easing.type: pressSpring.targetValue < 1 ? Easing.OutQuad : Easing.OutBack; easing.overshoot: 2.5 } }

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

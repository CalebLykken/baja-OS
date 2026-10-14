import QtQuick

// A switch-panel key: a rounded square with the style's border, an icon, and
// a little travel when pressed. `primary` makes it the screen's one main key
// (accent fill). Used for transport, volume and brightness.
Rectangle {
    id: btn
    property string icon     // a name from Icon.qml
    property bool primary: false
    property int size: Theme.touch
    property real iconRotation: 0   // e.g. a compass needle
    signal clicked()

    width: size
    height: size
    radius: Theme.radius
    border.width: Theme.border
    border.color: primary ? Theme.accent : Theme.line
    color: primary ? (tap.pressed ? Qt.darker(Theme.accent, 1.25) : Theme.accent)
                   : (tap.pressed ? Theme.line : Theme.panelHi)
    scale: tap.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 70 } }

    Icon {
        anchors.centerIn: parent
        name: btn.icon
        size: btn.size * 0.46
        rotation: btn.iconRotation
        color: btn.primary ? Theme.bg : Theme.text
    }

    TapHandler {
        id: tap
        onTapped: btn.clicked()
    }
}

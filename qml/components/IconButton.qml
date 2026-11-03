import QtQuick

// A switch-panel key: a rounded square with the style's border, an icon, and
// a little travel when pressed. `primary` makes it the screen's one main key
// (accent fill). Used for transport, volume and brightness.
// When `icon` changes after the key has loaded (play to pause, follow on/off)
// the old glyph shrinks and fades out while the new one grows in with a small
// overshoot and a twist (~180 ms; opacity, scale and rotation only). Nothing
// animates on first load, and a change to iconRotation alone just turns the
// icon at once.
Rectangle {
    id: btn
    property string icon     // a name from Icon.qml
    property bool primary: false
    property bool active: false     // a mode that's on (e.g. follow): accent outline and icon
    property int size: Theme.touch
    property real iconRotation: 0   // e.g. a compass needle
    signal clicked()

    width: size
    height: size
    radius: Theme.radius
    border.width: Theme.border
    border.color: primary || active ? Theme.accent : Theme.line
    color: primary ? (tap.pressed ? Qt.darker(Theme.accent, 1.25) : Theme.accent)
                   : (tap.pressed ? Theme.line : Theme.panelHi)
    scale: tap.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 70 } }

    property bool ready: false      // no swap animation while the page is being created
    property string shownIcon: ""   // the name `front` last showed, so a swap knows what to retire
    property real inRotation: 0     // the incoming icon's extra twist, degrees
    readonly property color iconColor: btn.primary ? Theme.bg : (btn.active ? Theme.accent : Theme.text)

    Component.onCompleted: {
        shownIcon = icon
        ready = true
    }

    onIconChanged: {
        if (!ready) {
            front.name = icon
            return
        }
        // A swap may still be running (fast double tap): jump to its end state first.
        swap.stop()
        back.opacity = 0
        back.scale = 1
        front.opacity = 1
        front.scale = 1
        inRotation = 0
        back.name = shownIcon
        front.name = icon
        shownIcon = icon
        swap.start()
    }

    // The outgoing icon; only visible during a swap.
    Icon {
        id: back
        anchors.centerIn: parent
        size: btn.size * 0.46
        rotation: btn.iconRotation
        color: btn.iconColor
        opacity: 0
        visible: opacity > 0
    }

    Icon {
        id: front
        anchors.centerIn: parent
        name: btn.icon
        size: btn.size * 0.46
        rotation: btn.iconRotation + btn.inRotation
        color: btn.iconColor
    }

    ParallelAnimation {
        id: swap
        NumberAnimation { target: back; property: "opacity"; from: 1; to: 0; duration: 180 }
        NumberAnimation { target: back; property: "scale"; from: 1; to: 0.6; duration: 180 }
        NumberAnimation { target: front; property: "opacity"; from: 0; to: 1; duration: 180 }
        NumberAnimation { target: front; property: "scale"; from: 0.6; to: 1; duration: 180; easing.type: Easing.OutBack }
        NumberAnimation { target: btn; property: "inRotation"; from: -30; to: 0; duration: 180; easing.type: Easing.OutBack }
    }

    TapHandler {
        id: tap
        onTapped: btn.clicked()
    }
}

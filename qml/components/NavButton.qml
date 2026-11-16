import QtQuick

// One entry in the left-hand navigation rail.
// The motion here is one-shot: the accent marker grows in and the icon pops only
// when the active page changes, and the card eases back from a press. Each run
// finishes within 280 ms and nothing loops or ticks, so the rail has no idle cost.
Item {
    id: btn
    property string icon
    property string label
    property bool active: false
    // A small accent dot on the icon's corner: something to look at on this
    // page (stored trouble codes, a waiting update). Hidden on the active page,
    // where the driver is already looking.
    property bool badge: false
    signal clicked()

    // Set once loading is done so the page active at startup doesn't animate.
    property bool ready: false
    Component.onCompleted: ready = true

    // Read-only views for tests/test_nav_button_motion.py.
    readonly property alias popRunning: pop.running
    readonly property alias glyphScale: glyph.scale
    readonly property alias markerHeight: marker.height
    readonly property alias cardHeight: card.height
    readonly property alias cardScale: card.scale
    readonly property alias cardWidth: card.width
    readonly property alias labelWidth: legend.contentWidth
    readonly property alias badgeShown: dot.visible

    onActiveChanged: {
        if (active && ready && visible)
            pop.restart()
        else if (!active) {
            pop.stop()
            glyph.scale = 1
        }
    }

    width: parent ? parent.width : 112
    height: 96

    SequentialAnimation {
        id: pop
        NumberAnimation { target: glyph; property: "scale"; to: 1.15; duration: 110; easing.type: Easing.OutQuad }
        NumberAnimation { target: glyph; property: "scale"; to: 1.0; duration: 170; easing.type: Easing.OutBack }
    }

    Rectangle {
        id: card
        anchors { fill: parent; margins: 8 }
        radius: Theme.radius
        color: btn.active ? Theme.panelHi : (tap.pressed ? Theme.panel : "transparent")
        Behavior on color { ColorAnimation { duration: 150 } }
        scale: tap.pressed ? 0.97 : 1
        // Press dips in 70 ms, release springs back in 180 ms (OutBack). The timing is
        // keyed on the Behavior's own target: tap.pressed is not yet re-evaluated
        // for this change when the animation starts, so it would pick the wrong curve.
        Behavior on scale {
            id: pressSpring
            NumberAnimation {
                duration: pressSpring.targetValue < 1 ? 70 : 180
                easing.type: pressSpring.targetValue < 1 ? Easing.OutQuad : Easing.OutBack
                easing.overshoot: 2.5
            }
        }

        Rectangle {
            id: marker
            visible: height > 0
            width: 4
            height: btn.active ? parent.height * 0.5 : 0
            Behavior on height {
                enabled: btn.ready
                NumberAnimation { duration: 220; easing.type: btn.active ? Easing.OutBack : Easing.InQuad }
            }
            radius: 2
            color: Theme.accent
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        }

        Column {
            anchors.centerIn: parent
            spacing: 6
            Icon {
                id: glyph
                anchors.horizontalCenter: parent.horizontalCenter
                name: btn.icon
                size: 34
                color: btn.active ? Theme.accent : Theme.textDim
                Behavior on color { ColorAnimation { duration: 150 } }

                // The badge dot: a plain shape, shown or hidden, with no
                // animation or timer of its own.
                Rectangle {
                    id: dot
                    visible: btn.badge && !btn.active
                    width: 14; height: 14; radius: 7
                    color: Theme.accent
                    border.width: 2
                    border.color: Theme.bg
                    anchors { right: parent.right; top: parent.top; rightMargin: -6; topMargin: -6 }
                }
            }
            Legend {
                id: legend
                anchors.horizontalCenter: parent.horizontalCenter
                // Keep the label inside the plate with a gap each side. The
                // widest label, SETTINGS, is about 100 px at 20 px caps, so Fit
                // shrinks it (to about 18 px) rather than letting it run past
                // the highlight. Tracking 1 keeps it close to the other labels.
                width: card.width - 12
                horizontalAlignment: Text.AlignHCenter
                fontSizeMode: Text.Fit
                minimumPixelSize: 15
                text: btn.label
                font.letterSpacing: 1
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

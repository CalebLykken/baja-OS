import QtQuick

// One equalizer band: a vertical column of segments, one per dB, lit from
// the zero line toward the setting (up to boost, down to cut). Tap or drag
// anywhere on it.
//
// Motion: the segments light from `shown`, a smoothed copy of `value`. When a
// preset changes `value`, a Behavior on `shown` glides it over to the new
// setting (after `delay`, so the panel can ripple low band to high band).
// Nothing runs at rest, and a finger drag is never delayed.
Item {
    id: s
    property int value: 0
    property int limit: 12
    property int delay: 0               // ms to wait before gliding (the ripple)
    property real shown: value          // what the segments draw
    signal moved(int value)

    readonly property int steps: limit * 2
    readonly property real gap: 2
    implicitWidth: 56

    // The Behavior intercepts each update of the `shown` binding and eases it
    // instead. It is disabled while a finger is down: it is checked when
    // `shown` changes, and by the first press's apply() the MouseArea is
    // already pressed, so even the first touch tracks instantly.
    Behavior on shown {
        enabled: !drag.pressed
        SequentialAnimation {
            PauseAnimation { duration: s.delay }
            NumberAnimation { target: s; property: "shown"; duration: 240; easing.type: Easing.OutCubic }
        }
    }

    Column {
        id: col
        width: Math.min(52, s.width)
        height: s.height
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: s.gap
        Repeater {
            model: s.steps
            Rectangle {
                // Segment i spans the dB range just below (limit - i).
                readonly property real mid: s.limit - index - 0.5
                readonly property bool lit: s.shown > 0 ? (mid > 0 && mid < s.shown)
                                          : (mid < 0 && mid > s.shown)
                width: col.width
                height: (col.height - (s.steps - 1) * s.gap) / s.steps
                radius: 2
                color: lit ? Theme.accent : Theme.panelHi
                Behavior on color { ColorAnimation { duration: 90 } }   // soften on/off
            }
        }
    }

    // The zero line.
    Rectangle {
        anchors { horizontalCenter: parent.horizontalCenter; verticalCenter: parent.verticalCenter }
        width: col.width + 14
        height: 2
        color: Theme.textDim
    }

    MouseArea {
        id: drag
        objectName: "eqDrag"
        anchors { fill: parent; leftMargin: -10; rightMargin: -10 }
        preventStealing: true          // don't let a scrolling page take the drag
        function apply(y) {
            // The segment under the finger lights: round away from zero,
            // with a small dead zone so the zero setting is still reachable.
            var raw = s.limit - y / height * s.steps
            var v = Math.abs(raw) < 0.5 ? 0 : (raw > 0 ? Math.ceil(raw) : Math.floor(raw))
            s.moved(Math.max(-s.limit, Math.min(s.limit, v)))
        }
        onPressed: (mouse) => apply(mouse.y)
        onPositionChanged: (mouse) => apply(mouse.y)
    }
}

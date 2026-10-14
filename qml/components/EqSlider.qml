import QtQuick

// One equalizer band: a vertical column of segments, one per dB, lit from
// the zero line toward the setting (up to boost, down to cut). Tap or drag
// anywhere on it.
Item {
    id: s
    property int value: 0
    property int limit: 12
    signal moved(int value)

    readonly property int steps: limit * 2
    readonly property real gap: 2
    implicitWidth: 56

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
                readonly property bool lit: s.value > 0 ? (mid > 0 && mid < s.value)
                                          : (mid < 0 && mid > s.value)
                width: col.width
                height: (col.height - (s.steps - 1) * s.gap) / s.steps
                radius: 2
                color: lit ? Theme.accent : Theme.panelHi
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
        anchors { fill: parent; leftMargin: -10; rightMargin: -10 }
        preventStealing: true          // don't let a scrolling page take the drag
        function apply(y) {
            var v = Math.round(s.limit - y / height * s.steps)
            s.moved(Math.max(-s.limit, Math.min(s.limit, v)))
        }
        onPressed: (mouse) => apply(mouse.y)
        onPositionChanged: (mouse) => apply(mouse.y)
    }
}

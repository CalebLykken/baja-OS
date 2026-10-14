import QtQuick

// A segmented level (volume, brightness) that echoes the segmented gauges:
// accent segments on, panelHi segments off. Tap or drag along it to set it;
// the touch area is taller than the bar so it's easy to hit while driving.
Item {
    id: bar
    property real value: 0          // 0..1
    property int segments: 20
    property bool interactive: true
    signal moved(real value)

    implicitHeight: 28

    Row {
        anchors.fill: parent
        spacing: 4
        Repeater {
            model: bar.segments
            Rectangle {
                width: (bar.width - (bar.segments - 1) * 4) / bar.segments
                height: bar.height
                radius: 2
                color: (index + 0.5) / bar.segments <= bar.value ? Theme.accent : Theme.panelHi
            }
        }
    }

    MouseArea {
        enabled: bar.interactive
        anchors { fill: parent; topMargin: -18; bottomMargin: -18 }
        preventStealing: true          // don't let a scrolling page take the drag
        function apply(x) { bar.moved(Math.max(0, Math.min(1, x / width))) }
        onPressed: (mouse) => apply(mouse.x)
        onPositionChanged: (mouse) => apply(mouse.x)
    }
}

import QtQuick

// A segmented level (volume, brightness) that echoes the segmented gauges:
// accent segments on, panelHi segments off. Tap or drag along it to set it;
// the touch area is taller than the bar so it's easy to hit while driving.
// End-stop bump: when the value arrives at full (or at zero) the last (or
// first) segment pops taller once, a detent you can see. It is a one-shot of
// about 250 ms, triggered only by the value arriving at 0 or 1. There is no
// timer and nothing runs while idle or at startup.
Item {
    id: bar
    property real value: 0          // 0..1
    property int segments: 20
    property bool interactive: true
    signal moved(real value)

    property real _prev: 0
    property bool ready: false
    property int bumpIndex: -1
    readonly property bool bumping: bump.running

    implicitHeight: 28

    Component.onCompleted: { _prev = value; ready = true }

    onValueChanged: {
        if (ready && visible) {
            if (_prev < 0.999 && value >= 0.999) doBump(segments - 1)
            else if (_prev > 0.001 && value <= 0.001) doBump(0)
        }
        _prev = value
    }

    function popAt(i) { var s = rep.itemAt(i); return s ? s.pop : -1 }

    function doBump(i) {
        bump.stop()                    // snap a bump in flight back to rest
        var old = rep.itemAt(bumpIndex)
        if (old) old.pop = 1
        var seg = rep.itemAt(i)
        if (!seg) return
        bumpIndex = i
        bumpUp.target = seg
        bumpDown.target = seg
        bump.start()
    }

    SequentialAnimation {
        id: bump
        NumberAnimation { id: bumpUp; property: "pop"; to: 1.45; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { id: bumpDown; property: "pop"; to: 1.0; duration: 160; easing.type: Easing.OutBack }
    }

    Row {
        anchors.fill: parent
        spacing: 4
        Repeater {
            id: rep
            model: bar.segments
            Rectangle {
                width: (bar.width - (bar.segments - 1) * 4) / bar.segments
                height: bar.height
                radius: 2
                property real pop: 1    // vertical scale, only the bump moves it
                transform: Scale { origin.y: height / 2; yScale: pop }
                color: (index + 0.5) / bar.segments <= bar.value ? Theme.accent : Theme.panelHi
                Behavior on color { ColorAnimation { duration: 90 } }
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

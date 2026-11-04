import QtQuick

// Thin bar for track progress, volume, and similar 0..1 values.
Rectangle {
    id: bar
    property real value: 0
    property color fill: Theme.accent

    // What the fill actually draws; follows value, except for the sweep below.
    property real shown: 0
    // Last clamped value, to tell a new track from an ordinary change.
    property real _prev: 0

    height: 6
    radius: 3
    color: Theme.line

    Rectangle {
        width: parent.width * parent.shown
        height: parent.height
        radius: parent.radius
        color: parent.fill
    }

    // One-shot drain back to the start; never loops or runs while idle.
    NumberAnimation {
        id: sweep
        target: bar
        property: "shown"
        duration: 280
        easing.type: Easing.OutCubic
    }

    Component.onCompleted: {
        var v = Math.max(0, Math.min(1, value))
        shown = v
        _prev = v
    }

    onValueChanged: {
        var v = Math.max(0, Math.min(1, value))
        // Only a drop from past halfway to within the first 5% (a new track,
        // or Previous restarting the song) sweeps. Everything else snaps: the
        // 1 s position ticks and forward jumps must not animate, and drags
        // must follow the finger. A tick arriving mid-sweep stops it and snaps,
        // so the bar always ends on the true position.
        if (_prev >= 0.5 && v <= 0.05 && bar.visible) {
            sweep.from = shown
            sweep.to = v
            sweep.restart()
        } else {
            sweep.stop()
            shown = v
        }
        _prev = v
    }
}

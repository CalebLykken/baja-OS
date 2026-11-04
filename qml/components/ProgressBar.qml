import QtQuick

// Thin bar for track progress, volume, and similar 0..1 values.
Rectangle {
    id: bar
    property real value: 0
    property color fill: Theme.accent

    // Read-only view of the seek-flash overlay's opacity (0 when idle).
    readonly property real flashOpacity: seekFlash.opacity

    // What the fill actually draws; follows value, except for the sweep below.
    property real shown: 0
    // Last clamped value, to tell a new track from an ordinary change.
    property real _prev: 0

    // Call when the user has just seeked (tap or drag release): brightens the
    // fill once. Never triggered by value changes, so 1 s ticks, drags and
    // track changes cannot flash.
    function flashSeek() {
        if (bar.visible)
            flash.restart()
    }

    height: 6
    radius: 3
    color: Theme.line

    Rectangle {
        width: parent.width * parent.shown
        height: parent.height
        radius: parent.radius
        color: parent.fill
    }

    // Seek acknowledgement: a lighter copy of the fill laid over it that
    // brightens once and fades. Invisible (not drawn) except for 280 ms after
    // flashSeek(); the bar's position is untouched.
    Rectangle {
        id: seekFlash
        objectName: "seekFlash"
        width: parent.width * parent.shown
        height: parent.height
        radius: parent.radius
        color: Qt.lighter(parent.fill, 1.5)
        opacity: 0
        visible: opacity > 0
    }

    // One-shot fade of the overlay; same timing as the sweep, ends by itself.
    NumberAnimation {
        id: flash
        target: seekFlash
        property: "opacity"
        from: 0.6
        to: 0
        duration: 280
        easing.type: Easing.OutCubic
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

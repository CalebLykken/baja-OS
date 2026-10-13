import QtQuick

// Arc gauge drawn with Canvas. Repaints only when the value moves enough to
// matter, which keeps it light on the Pi 2.
Card {
    id: g
    property string label
    property string unit
    property real value: 0
    property real minValue: 0
    property real maxValue: 100
    property real warnAbove: Number.POSITIVE_INFINITY
    property real warnBelow: Number.NEGATIVE_INFINITY
    property int decimals: 0

    readonly property bool warning: value > warnAbove || value < warnBelow
    readonly property real frac: clamp((value - minValue) / (maxValue - minValue))
    readonly property real warnFrac: isFinite(warnAbove)
                                     ? clamp((warnAbove - minValue) / (maxValue - minValue)) : 1

    function clamp(x) { return Math.max(0, Math.min(1, x)) }

    // Round to ~0.5% steps so tiny jitter doesn't trigger repaints.
    readonly property real paintFrac: Math.round(frac * 200) / 200
    onPaintFracChanged: arc.requestPaint()
    onWarningChanged: arc.requestPaint()

    Canvas {
        id: arc
        width: Math.min(parent.width - 24, parent.height - 24)
        height: width
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 8
        onWidthChanged: requestPaint()

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var cx = width / 2, cy = height / 2
            var r = width / 2 - 14
            if (r <= 0)
                return  // not laid out yet (e.g. a hidden page)
            var start = 0.75 * Math.PI
            var sweep = 1.5 * Math.PI
            ctx.lineCap = "round"

            // Track
            ctx.lineWidth = 12
            ctx.strokeStyle = "" + Theme.line
            ctx.beginPath()
            ctx.arc(cx, cy, r, start, start + sweep, false)
            ctx.stroke()

            // Redline zone, drawn as a thin outer band
            if (g.warnFrac < 1) {
                ctx.lineCap = "butt"
                ctx.lineWidth = 3
                ctx.strokeStyle = "" + Theme.warn
                ctx.beginPath()
                ctx.arc(cx, cy, r + 11, start + sweep * g.warnFrac, start + sweep, false)
                ctx.stroke()
                ctx.lineCap = "round"
            }

            // Value
            ctx.lineWidth = 12
            ctx.strokeStyle = "" + (g.warning ? Theme.warn : Theme.accent)
            ctx.beginPath()
            ctx.arc(cx, cy, r, start, start + sweep * Math.max(0.001, g.paintFrac), false)
            ctx.stroke()
        }
    }

    Column {
        anchors.centerIn: arc
        spacing: 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: g.value.toFixed(g.decimals)
            color: g.warning ? Theme.warn : Theme.text
            font.pixelSize: Math.max(28, arc.width * 0.22)
            font.weight: Font.DemiBold
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: g.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
    }

    Text {
        anchors { horizontalCenter: arc.horizontalCenter; bottom: arc.bottom; bottomMargin: 4 }
        text: g.label.toUpperCase()
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall - 2
        font.letterSpacing: 2
    }
}

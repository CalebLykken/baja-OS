import QtQuick

// Round gauge in one of three looks, picked by Theme.gauge:
//   arc       a value arc over a track (amber, rally)
//   needle    a classic dial: ticks, numerals and a sweeping needle (cluster)
//   segments  an arc of lit blocks like an LED bar graph (trail)
// Static parts are painted once; only what moves is redrawn, which keeps it
// light on the Pi 2.
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
    property real labelDivisor: 1   // e.g. 1000 so the RPM dial reads 0..7

    readonly property bool warning: value > warnAbove || value < warnBelow
    readonly property real frac: clamp((value - minValue) / (maxValue - minValue))
    readonly property real warnFrac: isFinite(warnAbove)
                                     ? clamp((warnAbove - minValue) / (maxValue - minValue)) : 1
    readonly property real warnLowFrac: isFinite(warnBelow)
                                        ? clamp((warnBelow - minValue) / (maxValue - minValue)) : 0
    readonly property string look: Theme.gauge
    readonly property string styleName: Theme.style

    // Dial geometry shared by every look: 270 degrees, opening at the bottom.
    readonly property real startAngle: 0.75 * Math.PI
    readonly property real sweep: 1.5 * Math.PI

    function clamp(x) { return Math.max(0, Math.min(1, x)) }

    // A tick step of 1, 2, 2.5 or 5 x 10^n giving 4-8 major ticks.
    function majorStep() {
        var range = maxValue - minValue
        var steps = [1, 2, 2.5, 5]
        for (var mag = Math.pow(10, Math.floor(Math.log(range) / Math.LN10) - 1); ; mag *= 10)
            for (var i = 0; i < steps.length; i++)
                if (range / (steps[i] * mag) <= 8) return steps[i] * mag
    }

    // Round to ~0.5% steps so tiny jitter doesn't trigger repaints.
    readonly property real paintFrac: Math.round(frac * 200) / 200
    onPaintFracChanged: if (look !== "needle") dynamic.requestPaint()
    onWarningChanged: dynamic.requestPaint()
    onStyleNameChanged: { face.requestPaint(); dynamic.requestPaint() }

    Item {
        id: dial
        width: Math.min(parent.width - 24, parent.height - 24)
        height: width
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 8
        readonly property real cx: width / 2
        readonly property real r: width / 2 - 14

        // Everything that doesn't move: track, ticks, numerals, redline.
        Canvas {
            id: face
            anchors.fill: parent
            onWidthChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var cx = dial.cx, r = dial.r
                if (r <= 0)
                    return  // not laid out yet (e.g. a hidden page)
                var a0 = g.startAngle, sw = g.sweep

                if (g.look === "needle") {
                    // Bezel ring and black face
                    ctx.beginPath()
                    ctx.arc(cx, cx, r + 10, 0, Math.PI * 2)
                    var bezel = ctx.createLinearGradient(0, 0, 0, cx * 2)
                    bezel.addColorStop(0, "#5a5f66")
                    bezel.addColorStop(0.5, "#1c1e22")
                    bezel.addColorStop(1, "#3a3e44")
                    ctx.fillStyle = bezel
                    ctx.fill()
                    ctx.beginPath()
                    ctx.arc(cx, cx, r + 4, 0, Math.PI * 2)
                    ctx.fillStyle = "#050506"
                    ctx.fill()

                    // Redline band
                    if (g.warnFrac < 1) {
                        ctx.lineWidth = 8
                        ctx.strokeStyle = "" + Theme.warn
                        ctx.beginPath()
                        ctx.arc(cx, cx, r - 6, a0 + sw * g.warnFrac, a0 + sw, false)
                        ctx.stroke()
                    }

                    // Minor and major ticks with numerals
                    var step = g.majorStep()
                    var minor = step / 5
                    var span = g.maxValue - g.minValue
                    ctx.fillStyle = "" + Theme.text
                    ctx.textAlign = "center"
                    ctx.textBaseline = "middle"
                    var px = Math.max(13, Math.round(r * 0.16))
                    ctx.font = "bold " + px + "px '" + (Theme.numFont || "sans-serif") + "'"
                    var first = Math.ceil(g.minValue / minor) * minor
                    for (var v = first; v <= g.maxValue + 1e-6; v += minor) {
                        var f = (v - g.minValue) / span
                        var a = a0 + sw * f
                        var major = Math.abs(v / step - Math.round(v / step)) < 1e-6
                        var len = major ? 16 : 8
                        ctx.lineWidth = major ? 3 : 1.5
                        var redZone = (g.warnFrac < 1 && f >= g.warnFrac - 1e-6)
                                      || f < g.warnLowFrac - 1e-6
                        ctx.strokeStyle = redZone ? "" + Theme.warn : "" + Theme.text
                        ctx.beginPath()
                        ctx.moveTo(cx + Math.cos(a) * r, cx + Math.sin(a) * r)
                        ctx.lineTo(cx + Math.cos(a) * (r - len), cx + Math.sin(a) * (r - len))
                        ctx.stroke()
                        if (major) {
                            var n = v / g.labelDivisor
                            var txt = Math.abs(n - Math.round(n)) < 1e-6 ? "" + Math.round(n) : n.toFixed(1)
                            var tr = r - len - px * 0.9
                            ctx.fillText(txt, cx + Math.cos(a) * tr, cx + Math.sin(a) * tr)
                        }
                    }
                    return
                }

                if (g.look === "segments") {
                    // Unlit blocks; the lit ones are drawn by `dynamic`.
                    dial.paintSegments(ctx, -1)
                    return
                }

                // arc: plain track plus a thin redline band outside it
                ctx.lineCap = "round"
                ctx.lineWidth = Theme.style === "rally" ? 16 : 12
                ctx.strokeStyle = "" + Theme.line
                ctx.beginPath()
                ctx.arc(cx, cx, r, a0, a0 + sw, false)
                ctx.stroke()
                if (g.warnFrac < 1) {
                    ctx.lineCap = "butt"
                    ctx.lineWidth = 3
                    ctx.strokeStyle = "" + Theme.warn
                    ctx.beginPath()
                    ctx.arc(cx, cx, r + 12, a0 + sw * g.warnFrac, a0 + sw, false)
                    ctx.stroke()
                }
            }
        }

        // The moving part for the arc and segment looks.
        Canvas {
            id: dynamic
            anchors.fill: parent
            visible: g.look !== "needle"
            onWidthChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                if (dial.r <= 0 || g.look === "needle")
                    return
                if (g.look === "segments") {
                    dial.paintSegments(ctx, g.paintFrac)
                    return
                }
                ctx.lineCap = "round"
                ctx.lineWidth = Theme.style === "rally" ? 16 : 12
                ctx.strokeStyle = "" + (g.warning ? Theme.warn : Theme.accent)
                ctx.beginPath()
                ctx.arc(dial.cx, dial.cx, dial.r, g.startAngle,
                        g.startAngle + g.sweep * Math.max(0.001, g.paintFrac), false)
                ctx.stroke()
            }
        }

        // Draws the block bar graph. lit < 0 paints every block unlit.
        function paintSegments(ctx, lit) {
            var count = 28
            var gapA = 0.022
            var segA = (g.sweep - gapA * (count - 1)) / count
            ctx.lineWidth = 18
            ctx.lineCap = "butt"
            for (var i = 0; i < count; i++) {
                var f = (i + 0.5) / count
                var hot = f >= g.warnFrac || f < g.warnLowFrac
                var on = lit >= 0 && f <= lit
                if (lit >= 0 && !on)
                    continue  // unlit blocks are already on the face
                // Lit blocks only turn red when the reading itself is out of
                // range; the warning zones just tint their unlit blocks.
                ctx.strokeStyle = on ? "" + (g.warning ? Theme.warn : Theme.accent)
                                     : "" + (hot ? Theme.accentDim : Theme.panelHi)
                var a = g.startAngle + i * (segA + gapA)
                ctx.beginPath()
                ctx.arc(dial.cx, dial.cx, dial.r - 4, a, a + segA, false)
                ctx.stroke()
            }
        }

        // Needle: a rotated rectangle, so moving it is a cheap GPU transform
        // and it can sweep smoothly between the ~5 Hz data updates.
        Item {
            visible: g.look === "needle"
            anchors.fill: parent
            rotation: (g.startAngle + g.sweep * g.frac) * 180 / Math.PI
            Behavior on rotation { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

            Rectangle {
                x: dial.cx - 14
                y: dial.cx - height / 2
                width: dial.r - 4 + 14
                height: 5
                radius: 2.5
                antialiasing: true
                color: Theme.accent
            }
        }
        Rectangle {
            visible: g.look === "needle"
            width: 26; height: 26; radius: 13
            anchors.centerIn: parent
            color: "#1d1f23"
            border.color: "#4a4f56"
            border.width: 2
        }
    }

    // Digital value: centred for arc/segments, below the hub for the needle.
    Column {
        anchors.horizontalCenter: dial.horizontalCenter
        anchors.verticalCenter: dial.verticalCenter
        anchors.verticalCenterOffset: g.look === "needle" ? dial.height * 0.24 : 0
        spacing: 0
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            numeric: true
            text: g.value.toFixed(g.decimals)
            color: g.warning ? Theme.warn : Theme.text
            font.pixelSize: g.look === "needle" ? Math.max(20, dial.width * 0.12)
                                                : Math.max(28, dial.width * 0.22)
            font.weight: Theme.numWeight
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: g.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
    }

    Label {
        anchors { horizontalCenter: dial.horizontalCenter; bottom: dial.bottom; bottomMargin: 4 }
        text: g.label.toUpperCase()
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall - 2
        font.letterSpacing: 2
    }
}

import QtQuick

// Round gauge in one of three looks, picked by Theme.gauge:
//   arc       a value arc over a track (amber, rally)
//   needle    a classic dial: ticks, numerals and a sweeping needle (cluster)
//   segments  an arc of lit blocks like an LED bar graph (trail): muted
//             while the reading is in range, with only the leading block
//             in the accent, so a gauge that needs looking at stands out
// Static parts are painted once; only what moves is redrawn, which keeps it
// light on the Pi 2.
// With peakHold a gauge remembers its highest real reading since start-up and
// marks it, like the tell-tale needle on a race tachometer: a dimmed block
// (segments), a tick across the track (arc) or a tick on the bezel (needle),
// in the warning colour if the peak was in a warning zone. The marker only
// shows once it is clearly above the live reading. Tap the gauge to clear it.
Card {
    id: g
    property string label
    property string unit
    property real value: 0
    property bool known: true       // false: no reading, so a dash and the needle at rest
    property real minValue: 0
    property real maxValue: 100
    property real warnAbove: Number.POSITIVE_INFINITY
    property real warnBelow: Number.NEGATIVE_INFINITY
    property int decimals: 0
    property real labelDivisor: 1   // e.g. 1000 so the RPM dial reads 0..7
    property bool peakHold: false   // remember and mark the highest reading
    property real peak: Number.NEGATIVE_INFINITY

    readonly property bool warning: known && (value > warnAbove || value < warnBelow)
    tappable: peakHold
    onTapped: peak = known ? value : Number.NEGATIVE_INFINITY
    // The peak follows real readings only, never the key-on sweep or the easing.
    // Not while the gauge is still being created: value, min/max and known are
    // bindings that settle one after another, and a handler writing peak in the
    // middle of that makes peakFrac and targetFrac binding loops that leave
    // peakFrac stale. onCompleted takes the first reading instead.
    property bool ready: false
    Component.onCompleted: {
        ready = true
        peak = peakHold && known ? value : Number.NEGATIVE_INFINITY
        updatePeakShown()
    }
    onValueChanged: if (ready && peakHold && known && value > peak) peak = value
    onKnownChanged: if (ready && peakHold && known && value > peak) peak = value
    // A units switch rescales min/max, so the old peak is meaningless. Clear it
    // rather than set it to value: value and min/max can update in either order.
    onMinValueChanged: if (ready) peak = Number.NEGATIVE_INFINITY
    onMaxValueChanged: if (ready) peak = Number.NEGATIVE_INFINITY
    // What's drawn eases toward the latest reading, so every look sweeps
    // smoothly between the ~5 Hz updates instead of jumping.
    property real shown: known ? value : minValue
    Behavior on shown { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    readonly property real frac: clamp((shown - minValue) / (maxValue - minValue))
    // Key-on self-test: while testFrac >= 0 the dial draws it instead of the
    // reading. The numerals and the warning colour still follow the real value.
    property real testFrac: -1
    // On the way back, testFrac is a blend weight toward the live reading, so
    // a value change mid-sweep is followed instead of snapping at the end.
    property bool sweepFalling: false
    readonly property real drawFrac: testFrac < 0 ? frac
                                     : (sweepFalling ? frac + (1 - frac) * testFrac : testFrac)
    readonly property real warnFrac: isFinite(warnAbove)
                                     ? clamp((warnAbove - minValue) / (maxValue - minValue)) : 1
    readonly property real warnLowFrac: isFinite(warnBelow)
                                        ? clamp((warnBelow - minValue) / (maxValue - minValue)) : 0
    readonly property real peakFrac: isFinite(peak)
                                     ? clamp((peak - minValue) / (maxValue - minValue)) : -1
    readonly property bool peakHot: isFinite(peak) && (peak > warnAbove || peak < warnBelow)
    readonly property string look: Theme.gauge
    readonly property string styleName: Theme.style

    // Dial geometry shared by every look: 270 degrees, opening at the bottom.
    readonly property real startAngle: 0.75 * Math.PI
    readonly property real sweep: 1.5 * Math.PI

    function clamp(x) { return Math.max(0, Math.min(1, x)) }

    // Sweep to full scale and back to the live reading, like a cluster's
    // key-on test. Ignored while one is running or before the dial has a size.
    function selfTest() {
        if (dial.r <= 0 || sweepAnim.running)
            return
        sweepAnim.start()
    }

    SequentialAnimation {
        id: sweepAnim
        ScriptAction { script: g.testFrac = 0 }
        NumberAnimation { target: g; property: "testFrac"; to: 1; duration: 550; easing.type: Easing.InOutCubic }
        PauseAnimation { duration: 120 }
        ScriptAction { script: g.sweepFalling = true }
        NumberAnimation { target: g; property: "testFrac"; from: 1; to: 0; duration: 550; easing.type: Easing.InOutCubic }
        ScriptAction { script: { g.testFrac = -1; g.sweepFalling = false } }
    }

    // A tick step of 1, 2, 2.5 or 5 x 10^n giving 4-8 major ticks.
    function majorStep() {
        var range = maxValue - minValue
        var steps = [1, 2, 2.5, 5]
        for (var mag = Math.pow(10, Math.floor(Math.log(range) / Math.LN10) - 1); ; mag *= 10)
            for (var i = 0; i < steps.length; i++)
                if (range / (steps[i] * mag) <= 8) return steps[i] * mag
    }

    // Round to ~0.5% steps so tiny jitter doesn't trigger repaints.
    readonly property real paintFrac: Math.round(drawFrac * 200) / 200
    onPaintFracChanged: if (look !== "needle") dynamic.requestPaint()
    // The peak marker shows only once the needle has really fallen back from
    // the peak. A new high is set the moment a sample arrives, while the eased
    // needle is still on its way up, so compare against the target (the latest
    // reading) as well as the eased position: the marker stays hidden on the
    // climb and appears when the needle eases down past it. It shows at 0.04
    // clear of the needle and hides again at 0.02, so a needle hovering near
    // the peak doesn't make it blink. Its repaints follow only those changes.
    readonly property real targetFrac: clamp(((known ? value : minValue) - minValue) / (maxValue - minValue))
    property bool peakShown: false
    function updatePeakShown() {
        if (!ready)
            return  // the bindings below are still settling; onCompleted calls this
        var ahead = peakFrac - Math.max(targetFrac, frac)
        var on = peakHold && peakFrac >= 0 && ahead > (peakShown ? 0.02 : 0.04)
        if (on !== peakShown)
            peakShown = on
    }
    onFracChanged: updatePeakShown()
    onTargetFracChanged: updatePeakShown()
    onPeakFracChanged: updatePeakShown()
    onPeakHoldChanged: updatePeakShown()
    onPeakShownChanged: dynamic.requestPaint()
    // While shown, the marker only moves when the peak is cleared (which hides
    // it), so this is just a safety net and is rare.
    readonly property real peakPaintFrac: Math.round(peakFrac * 200) / 200
    onPeakPaintFracChanged: if (peakShown) dynamic.requestPaint()
    onWarningChanged: dynamic.requestPaint()
    onStyleNameChanged: { face.requestPaint(); dynamic.requestPaint() }
    readonly property bool dark: Theme.dark          // day and night have their own colours
    onDarkChanged: { face.requestPaint(); dynamic.requestPaint() }

    // The face draws its numerals, ticks and redline from the scale, so a
    // units switch (which changes the range and limits) must repaint it.
    // A Connections block, so this can't clash with other handlers on g.
    Connections {
        target: g
        function onMinValueChanged() { face.requestPaint(); dynamic.requestPaint() }
        function onMaxValueChanged() { face.requestPaint(); dynamic.requestPaint() }
        function onLabelDivisorChanged() { face.requestPaint() }
        function onWarnFracChanged() { face.requestPaint(); dynamic.requestPaint() }
        function onWarnLowFracChanged() { face.requestPaint(); dynamic.requestPaint() }
    }

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

        // The moving part for the arc and segment looks; for the needle look
        // (whose needle is a rotated Rectangle) only the peak marker.
        Canvas {
            id: dynamic
            anchors.fill: parent
            visible: g.look !== "needle" || g.peakHold
            onWidthChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                if (dial.r <= 0)
                    return
                if (g.look === "segments") {
                    dial.paintSegments(ctx, g.paintFrac)
                } else if (g.look === "arc") {
                    ctx.lineCap = "round"
                    ctx.lineWidth = Theme.style === "rally" ? 16 : 12
                    ctx.strokeStyle = "" + (g.warning ? Theme.warn : Theme.accent)
                    ctx.beginPath()
                    ctx.arc(dial.cx, dial.cx, dial.r, g.startAngle,
                            g.startAngle + g.sweep * Math.max(0.001, g.paintFrac), false)
                    ctx.stroke()
                }
                if (g.peakShown)
                    dial.paintPeak(ctx)
            }
        }

        // The tell-tale marker at the held peak, in the accent (or the warning
        // colour if the peak was in a warning zone).
        function paintPeak(ctx) {
            var c = g.peakHot ? Theme.warn : Theme.accent
            var pf = g.peakPaintFrac
            if (g.look === "segments") {
                // The block at the peak, dimmer than the live leading block.
                var count = 28
                var gapA = 0.022
                var segA = (g.sweep - gapA * (count - 1)) / count
                var pi = Math.max(0, Math.min(count - 1, Math.floor(pf * count - 0.5)))
                var a = g.startAngle + pi * (segA + gapA)
                ctx.lineWidth = 18
                ctx.lineCap = "butt"
                ctx.strokeStyle = "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + ","
                                  + Math.round(c.b * 255) + ",0.55)"
                ctx.beginPath()
                ctx.arc(dial.cx, dial.cx, dial.r - 4, a, a + segA, false)
                ctx.stroke()
                return
            }
            // arc: a tick across the track; needle: a tick on the bezel
            var ang = g.startAngle + g.sweep * pf
            var inner = g.look === "needle" ? dial.r + 3 : dial.r - 10
            var outer = g.look === "needle" ? dial.r + 13 : dial.r + 10
            ctx.lineWidth = 3
            ctx.lineCap = "butt"
            ctx.strokeStyle = "" + c
            ctx.beginPath()
            ctx.moveTo(dial.cx + Math.cos(ang) * inner, dial.cx + Math.sin(ang) * inner)
            ctx.lineTo(dial.cx + Math.cos(ang) * outer, dial.cx + Math.sin(ang) * outer)
            ctx.stroke()
        }

        // Draws the block bar graph. lit < 0 paints every block unlit.
        function paintSegments(ctx, lit) {
            var count = 28
            var gapA = 0.022
            var segA = (g.sweep - gapA * (count - 1)) / count
            var tip = Math.floor(lit * count - 0.5)       // the leading lit block
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
                // The redline's unlit blocks are a dim red so the zone reads
                // as red, not brown. In range, the lit blocks are muted and
                // only the leading one is the accent, like a needle's tip.
                var w = Theme.warn
                ctx.strokeStyle = on ? "" + (g.warning ? Theme.warn : i === tip ? Theme.accent : Theme.textDim)
                                     : (hot ? "rgba(" + Math.round(w.r * 255) + "," + Math.round(w.g * 255) + ","
                                              + Math.round(w.b * 255) + ",0.3)"
                                            : "" + Theme.panelHi)
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
            rotation: (g.startAngle + g.sweep * g.drawFrac) * 180 / Math.PI

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
            text: g.known ? g.value.toFixed(g.decimals) : "—"
            color: g.warning ? Theme.warn : g.known ? Theme.text : Theme.textDim
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

    Legend {
        anchors { horizontalCenter: dial.horizontalCenter; bottom: dial.bottom; bottomMargin: 4 }
        text: g.label
    }
}

import QtQuick

// Full-window decoration behind the UI, one kind per style: topo contours
// (Trail), livery stripes (Rally), a perforated dot grid (Amber) and a
// tachometer face peeking in from a corner (Cluster). Painted once per size,
// style or colour change (day/night flips the theme colours), never per
// frame, so it costs nothing while driving.
Canvas {
    id: bd
    visible: Theme.backdrop !== "none"

    property string kind: Theme.backdrop
    // Theme colours, bound so a day/night or style switch repaints the canvas.
    // Canvas only repaints on requestPaint(), and kind does not change between
    // day and night, so these handlers are what keep the lines and stripes
    // in the right colours.
    property color lineColor: Theme.line
    property color accentColor: Theme.accent
    property color hiColor: Theme.panelHi
    onKindChanged: requestPaint()
    onLineColorChanged: requestPaint()
    onAccentColorChanged: requestPaint()
    onHiColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    // Fake topographic contours: rings of distorted circles around a few
    // "peaks". Deterministic so the map doesn't change between runs.
    function paintTopo(ctx) {
        var peaks = [[0.78, 0.30, 11], [0.25, 0.85, 9], [1.05, 0.95, 8]]
        ctx.strokeStyle = "" + lineColor
        ctx.lineWidth = 1.5
        ctx.globalAlpha = 0.8
        for (var p = 0; p < peaks.length; p++) {
            var cx = peaks[p][0] * width, cy = peaks[p][1] * height
            for (var ring = 1; ring <= peaks[p][2]; ring++) {
                var r = ring * 34
                ctx.beginPath()
                for (var i = 0; i <= 96; i++) {
                    var a = i / 96 * Math.PI * 2
                    var wobble = 1 + 0.16 * Math.sin(a * 3 + ring * 0.7 + p)
                                   + 0.07 * Math.sin(a * 7 + ring * 1.3)
                    var x = cx + Math.cos(a) * r * wobble * 1.25
                    var y = cy + Math.sin(a) * r * wobble
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
                }
                ctx.stroke()
            }
        }
    }

    // Two diagonal livery stripes sweeping up from the bottom-right corner.
    function paintStripes(ctx) {
        var colors = ["" + accentColor, "" + hiColor]
        var w = [70, 34]
        var x0 = width * 0.62
        ctx.globalAlpha = 0.24
        for (var i = 0; i < 2; i++) {
            var off = i * 92
            ctx.fillStyle = colors[i]
            ctx.beginPath()
            ctx.moveTo(x0 + off, height)
            ctx.lineTo(x0 + off + w[i], height)
            ctx.lineTo(width, height * 0.18 + off * 1.1 - w[i])
            ctx.lineTo(width, height * 0.18 + off * 1.1)
            ctx.closePath()
            ctx.fill()
        }
    }

    // Perforated-metal dot grid: one path of small dots, one fill.
    function paintGrid(ctx) {
        var pitch = 46
        ctx.globalAlpha = 0.5
        ctx.fillStyle = "" + lineColor
        ctx.beginPath()
        for (var y = pitch / 2; y < height; y += pitch) {
            for (var x = pitch / 2; x < width; x += pitch) {
                ctx.moveTo(x + 1.5, y)
                ctx.arc(x, y, 1.5, 0, Math.PI * 2)
            }
        }
        ctx.fill()
    }

    // One big faint tachometer face (0-8 ticks, redline at the end) peeking
    // in from the bottom-left. No numerals, so it can't pass for a real gauge.
    function paintDial(ctx) {
        var cx = width * 0.10, cy = height * 1.08, r = height * 0.55
        var a0 = 200 * Math.PI / 180, a1 = 340 * Math.PI / 180
        var red = a1 - (a1 - a0) * 0.12
        ctx.globalAlpha = 0.7
        ctx.strokeStyle = "" + lineColor
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.arc(cx, cy, r, a0, a1)
        ctx.stroke()
        for (var i = 0; i <= 16; i++) {
            var major = i % 2 === 0
            var a = a0 + (a1 - a0) * i / 16
            var len = major ? 22 : 12
            ctx.lineWidth = major ? 3 : 1.5
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r)
            ctx.lineTo(cx + Math.cos(a) * (r - len), cy + Math.sin(a) * (r - len))
            ctx.stroke()
        }
        ctx.globalAlpha = 0.35
        ctx.strokeStyle = "" + accentColor
        ctx.lineWidth = 6
        ctx.beginPath()
        ctx.arc(cx, cy, r, red, a1)
        ctx.stroke()
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (kind === "topo") paintTopo(ctx)
        else if (kind === "stripes") paintStripes(ctx)
        else if (kind === "grid") paintGrid(ctx)
        else if (kind === "dial") paintDial(ctx)
    }
}

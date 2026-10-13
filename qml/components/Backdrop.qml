import QtQuick

// Full-window decoration behind the UI. Painted once per size or style
// change, never per frame, so it costs nothing while driving.
Canvas {
    id: bd
    visible: Theme.backdrop !== "none"

    property string kind: Theme.backdrop
    onKindChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    // Fake topographic contours: rings of distorted circles around a few
    // "peaks". Deterministic so the map doesn't change between runs.
    function paintTopo(ctx) {
        var peaks = [[0.78, 0.30, 11], [0.25, 0.85, 9], [1.05, 0.95, 8]]
        ctx.strokeStyle = "" + Theme.line
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
        var colors = ["" + Theme.accent, "" + Theme.panelHi]
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

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (kind === "topo") paintTopo(ctx)
        else if (kind === "stripes") paintStripes(ctx)
    }
}

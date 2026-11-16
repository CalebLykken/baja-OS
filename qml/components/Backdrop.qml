import QtQuick

// Full-window decoration behind the UI, one kind per style: topo contours
// (Trail), livery stripes (Rally), a perforated dot grid (Amber), a
// tachometer face peeking in from a corner (Cluster), rolling sine waves
// (Atlantic), layered sand ridgelines (Desert), low-poly ice facets (Glacier)
// and CRT scanlines (LCD). Painted once per size,
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

    // Nine sine lines across the lower 65 percent of the window, 40 px apart,
    // each with its own amplitude, wavelength and phase. Deterministic.
    function paintWaves(ctx) {
        ctx.strokeStyle = "" + lineColor
        ctx.lineWidth = 1.5
        ctx.globalAlpha = 0.7
        var top = height * 0.35
        for (var i = 0; i < 9; i++) {
            var base = top + i * 40
            var amp = 10 + (i * 5) % 13
            var len = 260 + (i * 47) % 161
            var phase = i * 1.7
            ctx.beginPath()
            for (var x = 0; x <= width + 12; x += 12) {
                var y = base + amp * Math.sin(x / len * Math.PI * 2 + phase)
                if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
            }
            ctx.stroke()
        }
    }

    // Four layered dune ridgelines rising from the bottom, back to front,
    // each a base height plus two sines, filled faintly and edged.
    function paintDunes(ctx) {
        var bases = [0.62, 0.72, 0.82, 0.92]
        ctx.strokeStyle = "" + lineColor
        ctx.fillStyle = "" + hiColor
        ctx.lineWidth = 1.5
        for (var layer = 0; layer < 4; layer++) {
            var base = height * bases[layer]
            ctx.globalAlpha = 0.10 + 0.04 * layer
            ctx.beginPath()
            ctx.moveTo(0, height)
            for (var x = 0; x <= width + 12; x += 12) {
                var y = base + 18 * Math.sin(x / 310 + layer * 1.9)
                               + 8 * Math.sin(x / 120 + layer * 0.8)
                ctx.lineTo(x, y)
            }
            ctx.lineTo(width + 12, height)
            ctx.closePath()
            ctx.fill()
            // Edge the ridge only, not the closing sides and bottom.
            ctx.globalAlpha = 0.7
            ctx.beginPath()
            for (var x2 = 0; x2 <= width + 12; x2 += 12) {
                var y2 = base + 18 * Math.sin(x2 / 310 + layer * 1.9)
                                + 8 * Math.sin(x2 / 120 + layer * 0.8)
                if (x2 === 0) ctx.moveTo(x2, y2); else ctx.lineTo(x2, y2)
            }
            ctx.stroke()
        }
    }

    // Deterministic 0..1 hash of a vertex, so the facets never move between runs.
    function hash(i, j, seed) {
        var v = Math.sin(i * 12.9898 + j * 78.233 + seed) * 43758.5453
        return v - Math.floor(v)
    }

    // Low-poly ice: a 9 x 6 grid of vertices, each jittered up to 30 percent
    // of a cell, every cell split into two triangles. Edges are stroked and
    // every third triangle is filled faintly. Only triangles right of 35
    // percent of the width or above 40 percent of the height are drawn, so
    // the lower left stays calm behind the text.
    function paintFacets(ctx) {
        var cols = 9, rows = 6
        var cw = width / (cols - 1), ch = height / (rows - 1)
        var vx = [], vy = []
        for (var j = 0; j < rows; j++) {
            for (var i = 0; i < cols; i++) {
                var edgeX = i === 0 || i === cols - 1
                var edgeY = j === 0 || j === rows - 1
                vx.push(i * cw + (edgeX ? 0 : (hash(i, j, 0) - 0.5) * 0.6 * cw))
                vy.push(j * ch + (edgeY ? 0 : (hash(i, j, 5.1) - 0.5) * 0.6 * ch))
            }
        }
        ctx.strokeStyle = "" + lineColor
        ctx.fillStyle = "" + hiColor
        ctx.lineWidth = 1.2
        var n = 0
        for (var cj = 0; cj < rows - 1; cj++) {
            for (var ci = 0; ci < cols - 1; ci++) {
                var a = cj * cols + ci, b = a + 1, c = a + cols, d = c + 1
                var tris = [[a, b, c], [b, d, c]]
                for (var t = 0; t < 2; t++) {
                    var v = tris[t]
                    var mx = (vx[v[0]] + vx[v[1]] + vx[v[2]]) / 3
                    var my = (vy[v[0]] + vy[v[1]] + vy[v[2]]) / 3
                    n++
                    if (mx < width * 0.35 && my > height * 0.40) continue
                    ctx.beginPath()
                    ctx.moveTo(vx[v[0]], vy[v[0]])
                    ctx.lineTo(vx[v[1]], vy[v[1]])
                    ctx.lineTo(vx[v[2]], vy[v[2]])
                    ctx.closePath()
                    if (n % 3 === 0) {
                        ctx.globalAlpha = 0.12
                        ctx.fill()
                    }
                    ctx.globalAlpha = 0.5
                    ctx.stroke()
                }
            }
        }
    }

    // CRT scanlines: one horizontal line every 4 px, one path, one stroke.
    function paintScanlines(ctx) {
        ctx.strokeStyle = "" + lineColor
        ctx.lineWidth = 1
        ctx.globalAlpha = 0.22
        ctx.beginPath()
        for (var y = 2; y < height; y += 4) {
            ctx.moveTo(0, y)
            ctx.lineTo(width, y)
        }
        ctx.stroke()
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (kind === "topo") paintTopo(ctx)
        else if (kind === "stripes") paintStripes(ctx)
        else if (kind === "grid") paintGrid(ctx)
        else if (kind === "dial") paintDial(ctx)
        else if (kind === "waves") paintWaves(ctx)
        else if (kind === "dunes") paintDunes(ctx)
        else if (kind === "facets") paintFacets(ctx)
        else if (kind === "scanlines") paintScanlines(ctx)
    }
}

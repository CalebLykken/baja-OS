import QtQuick
import "IconPaths.js" as IconPaths

// A Material Design icon (Apache 2.0, github.com/google/material-design-icons),
// drawn from its SVG path on a 24x24 grid. The path table lives in IconPaths.js
// so it is parsed once and shared by every Icon. Canvas parses SVG path data
// natively, so there's no icon font or Qt SVG module to install on the Pi,
// and icons stay sharp at any size and follow the style's colors.
Canvas {
    id: icon
    property string name
    property color color: Theme.text
    property real size: 32

    width: size
    height: size

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onSizeChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var d = IconPaths.paths[name]
        if (!d)
            return
        ctx.scale(width / 24, height / 24)
        ctx.fillStyle = "" + color
        ctx.path = d
        ctx.fill()
    }
}

import QtQuick

// A Material Design icon (Apache 2.0, github.com/google/material-design-icons),
// drawn from its SVG path on a 24x24 grid. Canvas parses SVG path data
// natively, so there's no icon font or Qt SVG module to install on the Pi,
// and icons stay sharp at any size and follow the style's colors.
Canvas {
    id: icon
    property string name
    property color color: Theme.text
    property real size: 32

    width: size
    height: size

    readonly property var paths: ({
        play: "M8 5v14l11-7z",
        pause: "M6 19h4V5H6v14zm8-14v14h4V5h-4z",
        next: "M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z",
        previous: "M6 6h2v12H6zm3.5 6l8.5 6V6z",
        home: "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
        music: "M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z",
        map: "M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z",
        speed: "M20.38 8.57l-1.23 1.85a8 8 0 0 1-.22 7.58H5.07A8 8 0 0 1 15.58 6.85l1.85-1.23A10 10 0 0 0 3.35 19a2 2 0 0 0 1.72 1h13.85a2 2 0 0 0 1.74-1 10 10 0 0 0-.27-10.44zm-9.79 6.84a2 2 0 0 0 2.83 0l5.66-8.49-8.49 5.66a2 2 0 0 0 0 2.83z",
        settings: "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
        navigation: "M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z",
        add: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
        remove: "M19 13H5v-2h14v2z",
        equalizer: "M10 20h4V4h-4v16zm-6 0h4v-8H4v8zM16 9v11h4V9h-4z"
    })

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onSizeChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var d = paths[name]
        if (!d)
            return
        ctx.scale(width / 24, height / 24)
        ctx.fillStyle = "" + color
        ctx.path = d
        ctx.fill()
    }
}

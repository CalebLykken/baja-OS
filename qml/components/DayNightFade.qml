import QtQuick

// A soft fade when the dashboard turns from day to night or back (the sun
// going down, or Appearance changed in Settings). The colour of the scheme
// just left covers the whole screen and fades out over half a second, so the
// change isn't one hard flip. It runs only on a change: no timer, no loop,
// and nothing is drawn while it is clear. No MouseArea, so it never takes a
// tap. Off until `armed`, so the first day or night setting at start-up
// never fades. Main.qml arms it once the start-up screen is gone.
Rectangle {
    id: fade
    property bool armed: false
    color: Theme.bg
    opacity: 0
    visible: opacity > 0

    Connections {
        target: Theme
        function onDarkChanged() {
            if (!fade.armed) return
            // Theme.dark is already the new scheme, so the colour to hold is
            // the one it just left.
            // A style without a day set stays on its night colours by day.
            fade.color = Theme.dark ? (Theme.lightStyles[Theme.style] || Theme.base).bg
                                    : Theme.base.bg
            fade.opacity = 1
            fadeOut.restart()
        }
    }

    NumberAnimation {
        id: fadeOut
        target: fade
        property: "opacity"
        to: 0
        duration: 500
        easing.type: Easing.OutCubic
    }
}

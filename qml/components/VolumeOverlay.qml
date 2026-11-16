import QtQuick

// Level panel for the dash knob: a small pill at the bottom centre that
// shows the volume (or a muted speaker) for about two seconds after it
// changes, then fades out. Without it the knob is blind on every page but
// Music.
//
// One SequentialAnimation (fade in, hold, fade out) is restarted on each
// change, so a run of knob clicks keeps it up and then lets it go. At
// opacity 0 it is not visible, so nothing draws or runs when idle. There is
// no input handler: it never takes a tap.
//
// `ready` is set by Main once the splash is gone, so the saved volume being
// restored at start-up doesn't pop it. `quiet` is set on the page that has
// its own volume bar (Music).
Card {
    id: overlay
    property bool ready: false
    property bool quiet: false

    readonly property bool hasMedia: typeof media !== "undefined"
    readonly property bool muted: hasMedia && media.muted
    readonly property int level: hasMedia ? Math.round(media.volume) : 0

    // Bottom centre of the area right of the nav rail (rail is 112 px wide).
    anchors {
        bottom: parent.bottom; bottomMargin: 24
        horizontalCenter: parent.horizontalCenter; horizontalCenterOffset: 56
    }
    width: row.implicitWidth + 48
    height: 72
    opacity: 0
    visible: opacity > 0

    function pop() {
        if (!ready || quiet) return
        show.restart()
    }

    onQuietChanged: if (quiet) { show.stop(); opacity = 0 }

    Connections {
        target: overlay.hasMedia ? media : null
        function onVolumeChanged() { overlay.pop() }
        function onMutedChanged() { overlay.pop() }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 16

        Icon {
            id: speaker
            anchors.verticalCenter: parent.verticalCenter
            name: overlay.muted ? "volume_off" : "volume"
            size: 36
            color: overlay.muted ? Theme.textDim : Theme.text
        }
        ProgressBar {
            anchors.verticalCenter: parent.verticalCenter
            width: 240
            height: 10
            radius: 5
            value: overlay.level / 100
            fill: overlay.muted ? Theme.textDim : Theme.accent
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            width: 56
            horizontalAlignment: Text.AlignRight
            text: overlay.level
            numeric: true
            color: overlay.muted ? Theme.textDim : Theme.text
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
        }
    }

    SequentialAnimation {
        id: show
        NumberAnimation { target: overlay; property: "opacity"; to: 1; duration: 150 }
        PauseAnimation { duration: 1400 }
        NumberAnimation { target: overlay; property: "opacity"; to: 0; duration: 300 }
    }
}

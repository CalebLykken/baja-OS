import QtQuick

// Where the music is coming from, in plain words: "Spotify", the phone's
// name over Bluetooth, or "On this Pi". Quiet text, no brand colour.
// A change of source is one short moment: the old text slides out to the
// left and fades, then the new text slides in from the right.
Row {
    id: badge
    readonly property string src: media.source
    readonly property string wantText: src === "local" ? "On this Pi" : (media.sourceName || "Phone")
    readonly property string wantIcon: src === "phone" ? "bluetooth" : "music"
    // What is on screen now. It lags wantText during the swap, so a
    // change that arrives mid-swap is picked up when the swap lands.
    property string shownText
    property string shownIcon
    // The first values arrive while the badge is being built; they are
    // shown as they are, with no swap.
    property bool ready: false
    spacing: 8
    transform: Translate { id: shift }

    Component.onCompleted: {
        shownText = wantText
        shownIcon = wantIcon
        ready = true
    }

    // Only a real change of the words or icon moves the badge. A repeat
    // of the same source (a status refresh) does nothing.
    function kick() {
        if (!ready || (wantText === shownText && wantIcon === shownIcon))
            return
        if (!visible) {
            swap.stop()
            shownText = wantText
            shownIcon = wantIcon
            opacity = 1
            shift.x = 0
            return
        }
        swap.restart()
    }
    onWantTextChanged: kick()
    onWantIconChanged: kick()

    SequentialAnimation {
        id: swap
        ParallelAnimation {
            NumberAnimation { target: badge; property: "opacity"; to: 0; duration: 110; easing.type: Easing.InQuad }
            NumberAnimation { target: shift; property: "x"; to: -10; duration: 110; easing.type: Easing.InQuad }
        }
        // Read the wanted values when this runs, not when the swap began.
        ScriptAction {
            script: {
                badge.shownText = badge.wantText
                badge.shownIcon = badge.wantIcon
                shift.x = 10
            }
        }
        ParallelAnimation {
            NumberAnimation { target: badge; property: "opacity"; to: 1; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "x"; to: 0; duration: 180; easing.type: Easing.OutCubic }
        }
    }

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: parent.shownIcon
        size: 18
        color: Theme.textDim
    }
    Label {
        anchors.verticalCenter: parent.verticalCenter
        text: parent.shownText
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        font.weight: Font.DemiBold
    }
}

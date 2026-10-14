import QtQuick

// Where the music is coming from: Spotify (green), the phone over Bluetooth,
// or this Pi's own library.
Row {
    id: badge
    property bool showLocal: false     // also label the Pi's own library
    readonly property string src: media.source
    visible: src !== "local" || showLocal
    spacing: 8

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: badge.src === "phone" ? "bluetooth" : "music"
        size: 20
        color: badge.src === "spotify" ? "#1ed760" : Theme.accent     // Spotify green
    }
    Label {
        anchors.verticalCenter: parent.verticalCenter
        text: badge.src === "local" ? "ON THIS PI" : (media.sourceName || "PHONE").toUpperCase()
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall - 2
        font.letterSpacing: 1.5
    }
}

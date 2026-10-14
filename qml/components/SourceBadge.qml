import QtQuick

// Where the music is coming from, in plain words: "Spotify", the phone's
// name over Bluetooth, or "On this Pi". Quiet text, no brand colour.
Row {
    readonly property string src: media.source
    spacing: 8

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: parent.src === "phone" ? "bluetooth" : "music"
        size: 18
        color: Theme.textDim
    }
    Label {
        anchors.verticalCenter: parent.verticalCenter
        text: parent.src === "local" ? "On this Pi" : (media.sourceName || "Phone")
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        font.weight: Font.DemiBold
    }
}

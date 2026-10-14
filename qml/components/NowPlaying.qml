import QtQuick
import QtQuick.Layouts

// The Home screen's now-playing card: the album art (rounded, glowing in its
// own colours), title and artist, progress, and transport controls. The play
// button and progress bar take the cover's colour. A badge shows when the
// music comes from Spotify or the phone. Tap the art to open Music.
Card {
    id: np
    signal openMusic()

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    heading: "Now playing"

    readonly property bool fromPhone: media.source === "phone"
    readonly property color tint: media.artColor !== "" ? media.artColor : Theme.accent

    SourceBadge {
        anchors { right: parent.right; top: parent.top; rightMargin: 20; topMargin: 12 }
    }

    RowLayout {
        anchors { fill: parent; margins: 24; topMargin: 52 }
        spacing: 28

        AlbumArt {
            Layout.preferredWidth: Math.min(parent.height, parent.width * 0.5)
            Layout.preferredHeight: Layout.preferredWidth
            Layout.alignment: Qt.AlignVCenter
            source: media.artCard
            glowSource: media.artGlow
            placeholder: np.fromPhone ? "phone" : "music"
            TapHandler { onTapped: np.openMusic() }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 8

            Label {
                Layout.fillWidth: true
                text: media.title
                font.pixelSize: 34
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: media.artist
                color: Theme.textDim
                font.pixelSize: 24
                elide: Text.ElideRight
            }

            ProgressBar {
                Layout.fillWidth: true
                Layout.topMargin: 14
                Layout.preferredHeight: 8
                radius: 4
                value: media.duration > 0 ? media.position / media.duration : 0
                fill: np.tint
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: np.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Item { Layout.fillWidth: true }
                Label { text: np.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            }

            Row {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6
                spacing: 18
                IconButton { icon: "previous"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                IconButton {
                    icon: media.playing ? "pause" : "play"
                    primary: true
                    fill: np.tint
                    size: 96
                    onClicked: media.togglePlay()
                }
                IconButton { icon: "next"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
            }
        }
    }
}

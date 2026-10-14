import QtQuick
import QtQuick.Layouts

// The Home screen's music card: the cover as a framed print beside where the
// music comes from, title and artist; progress and the transport keys run
// across underneath. No heading: a song explains itself. Tap the cover to
// open Music.
Card {
    id: np
    signal openMusic()

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    ColumnLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 6

        // A plain Item, so the cover can size itself from the space the
        // column gives this row without a layout loop.
        Item {
            id: top
            Layout.fillWidth: true
            Layout.fillHeight: true

            AlbumArt {
                id: art
                // Leave room for the print's offset shadow below and right.
                width: Math.min(top.height - 12, top.width * 0.52)
                height: width
                anchors { left: parent.left; verticalCenter: parent.verticalCenter; verticalCenterOffset: -4 }
                source: media.artCard
                placeholder: media.source === "phone" ? "phone" : "music"
                TapHandler { onTapped: np.openMusic() }
            }

            ColumnLayout {
                anchors { left: art.right; leftMargin: 26; right: parent.right; verticalCenter: art.verticalCenter }
                spacing: 6

                SourceBadge {}
                Label {
                    Layout.fillWidth: true
                    Layout.topMargin: 2
                    text: media.title
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: media.artist
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.topMargin: 14
            value: media.duration > 0 ? media.position / media.duration : 0
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: np.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            Item { Layout.fillWidth: true }
            Label { text: np.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
        }

        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            IconButton { icon: "previous"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
            IconButton {
                icon: media.playing ? "pause" : "play"
                primary: true
                size: 96
                onClicked: media.togglePlay()
            }
            IconButton { icon: "next"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
        }
    }
}

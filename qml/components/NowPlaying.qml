import QtQuick
import QtQuick.Layouts

// Now-playing card shared by the Home and Music pages: art placeholder,
// title/artist, progress, and transport controls.
Card {
    id: np
    property bool compact: false
    signal openMusic()

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    heading: "Now playing"

    RowLayout {
        anchors { fill: parent; margins: 24; topMargin: 52 }
        spacing: 24

        // Album art placeholder
        Rectangle {
            Layout.preferredWidth: Math.min(parent.height, parent.width * 0.4)
            Layout.preferredHeight: Layout.preferredWidth
            Layout.alignment: Qt.AlignVCenter
            radius: Theme.radius
            color: Theme.accentDim
            Text {
                anchors.centerIn: parent
                text: "♫"
                color: Theme.accent
                font.pixelSize: parent.width * 0.4
            }
            TapHandler { onTapped: np.openMusic() }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 10

            Text {
                Layout.fillWidth: true
                text: media.title
                color: Theme.text
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: media.artist
                color: Theme.textDim
                font.pixelSize: Theme.fontBody
                elide: Text.ElideRight
            }

            ProgressBar {
                Layout.fillWidth: true
                Layout.topMargin: 12
                value: media.duration > 0 ? media.position / media.duration : 0
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: np.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Item { Layout.fillWidth: true }
                Text { text: np.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            }

            Row {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 8
                spacing: 24
                IconButton { glyph: "◀◀"; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                IconButton {
                    glyph: media.playing ? "❚❚" : "▶"
                    primary: true
                    size: Theme.touch + 16
                    onClicked: media.togglePlay()
                }
                IconButton { glyph: "▶▶"; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
            }
        }
    }
}

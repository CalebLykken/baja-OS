import QtQuick
import QtQuick.Layouts

// Now-playing card shared by the Home and Music pages: art (or a placeholder),
// title/artist, progress, and transport controls. Shows a Bluetooth badge
// when the music is coming from the phone.
Card {
    id: np
    property bool compact: false
    signal openMusic()

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    heading: "Now playing"

    readonly property bool fromPhone: media.source === "phone"
    readonly property color tint: media.artColor !== "" ? media.artColor : Theme.accent

    Row {
        visible: np.fromPhone
        anchors { right: parent.right; top: parent.top; rightMargin: 20; topMargin: 12 }
        spacing: 6
        Icon { name: "bluetooth"; size: 20; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: media.sourceName || "Phone"
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall - 2
            font.letterSpacing: 1
        }
    }

    RowLayout {
        anchors { fill: parent; margins: 24; topMargin: 52 }
        spacing: 24

        // Album art, or a music note icon when the track has none
        Rectangle {
            Layout.preferredWidth: Math.min(parent.height, parent.width * 0.4)
            Layout.preferredHeight: Layout.preferredWidth
            Layout.alignment: Qt.AlignVCenter
            radius: Theme.radius
            color: Theme.accentDim
            clip: true
            Icon {
                visible: art.status !== Image.Ready
                anchors.centerIn: parent
                name: np.fromPhone ? "phone" : "music"
                color: Theme.accent
                size: parent.width * 0.45
            }
            Image {
                id: art
                anchors.fill: parent
                source: media.art
                fillMode: Image.PreserveAspectCrop
                // Decode at display size; embedded covers can be 3000 px PNGs.
                sourceSize { width: 400; height: 400 }
                asynchronous: true
                smooth: true
            }
            TapHandler { onTapped: np.openMusic() }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 10

            Label {
                Layout.fillWidth: true
                text: media.title
                color: Theme.text
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Label {
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
                Layout.topMargin: 8
                spacing: 24
                IconButton { icon: "previous"; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                IconButton {
                    icon: media.playing ? "pause" : "play"
                    primary: true
                    size: Theme.touch + 16
                    onClicked: media.togglePlay()
                }
                IconButton { icon: "next"; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
            }
        }
    }
}

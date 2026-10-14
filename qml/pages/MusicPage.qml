import QtQuick
import QtQuick.Layouts
import "../components"

// The album art is the star: as large as fits on the left, glowing in its own
// colours, over a blurred copy of itself. On the right: what's playing,
// progress, big controls, volume, and what's next. The play button and
// progress bar take the cover's colour.
Item {
    id: page
    signal navigate(int index)

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    readonly property color tint: media.artColor !== "" ? media.artColor : Theme.accent
    readonly property real glass: backdrop.active ? 0.5 : 0

    ArtBackdrop {
        id: backdrop
        anchors.fill: parent
        strength: 0.6
    }

    RowLayout {
        anchors { fill: parent; leftMargin: 8; rightMargin: 4 }
        spacing: 36

        // ---- the cover ----------------------------------------------------
        Item {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.min(height, page.width * 0.43)

            AlbumArt {
                anchors.centerIn: parent
                width: Math.min(parent.width, parent.height) - 48
                height: width
                source: media.artCard
                glowSource: media.artGlow
                placeholder: media.source === "phone" ? "phone" : "music"
            }
        }

        // ---- what's playing, controls, up next ----------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 6

            SourceBadge {
                Layout.topMargin: 6
                showLocal: true
            }
            Label {
                Layout.fillWidth: true
                Layout.topMargin: 4
                text: media.title
                font.pixelSize: 40
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: media.artist
                color: Theme.textDim
                font.pixelSize: 26
                elide: Text.ElideRight
            }

            ProgressBar {
                Layout.fillWidth: true
                Layout.topMargin: 16
                Layout.preferredHeight: 8
                radius: 4
                value: media.duration > 0 ? media.position / media.duration : 0
                fill: page.tint
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: page.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Item { Layout.fillWidth: true }
                Label { text: page.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            }

            // Transport, centred under the progress bar.
            Row {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 4
                spacing: 28
                IconButton { icon: "previous"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                IconButton {
                    icon: media.playing ? "pause" : "play"
                    primary: true
                    fill: page.tint
                    size: 108
                    onClicked: media.togglePlay()
                }
                IconButton { icon: "next"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
            }

            // Volume: big - and + either side of the level.
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 16
                IconButton { icon: "remove"; size: 60; onClicked: media.volumeDown() }
                ProgressBar {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 8
                    radius: 4
                    value: media.volume / 100
                    fill: page.tint
                }
                Label {
                    Layout.preferredWidth: 44
                    horizontalAlignment: Text.AlignRight
                    text: media.volume
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody - 2
                }
                IconButton { icon: "add"; size: 60; onClicked: media.volumeUp() }
            }

            // Spotify: what it plays next (display only). Otherwise the Pi's
            // own music; while the phone plays, tap a song to switch.
            Card {
                id: listCard
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: 12
                glass: page.glass
                readonly property bool spotifyQueue: media.source === "spotify"
                heading: spotifyQueue ? "Up next on Spotify"
                         : media.source === "phone" ? "Library · tap a song to switch" : "Library"

                ListView {
                    id: queue
                    anchors { fill: parent; margins: 10; topMargin: 44 }
                    clip: true
                    model: listCard.spotifyQueue ? media.upNext : media.queue
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool current: index === media.index

                        width: queue.width
                        height: 64
                        radius: Theme.radius - 6
                        color: current ? Qt.rgba(page.tint.r, page.tint.g, page.tint.b, 0.16)
                                       : (rowTap.pressed ? Theme.line : "transparent")

                        Item {
                            id: num
                            width: 40
                            height: parent.height
                            anchors { left: parent.left; leftMargin: 12 }
                            Icon {
                                visible: current
                                anchors.verticalCenter: parent.verticalCenter
                                name: "equalizer"
                                size: 22
                                color: page.tint
                            }
                            Label {
                                visible: !current
                                anchors.verticalCenter: parent.verticalCenter
                                text: index + 1
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                        Column {
                            anchors {
                                left: num.right; right: parent.right; rightMargin: 12
                                verticalCenter: parent.verticalCenter
                            }
                            Label {
                                width: parent.width
                                text: modelData.title
                                color: current ? page.tint : Theme.text
                                font.pixelSize: Theme.fontBody - 2
                                elide: Text.ElideRight
                            }
                            Label {
                                width: parent.width
                                text: modelData.artist
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall - 2
                                elide: Text.ElideRight
                            }
                        }
                        TapHandler {
                            id: rowTap
                            onTapped: if (!listCard.spotifyQueue) media.playIndex(index)
                        }
                    }
                }
            }
        }
    }
}

import QtQuick
import QtQuick.Layouts
import "../components"

// Now playing on the left; tappable queue and volume on the right, over a
// blurred, darkened copy of the album art.
Item {
    id: page
    signal navigate(int index)

    readonly property bool hasBackdrop: media.artBlur !== ""

    // The art is pre-shrunk to ~24 px in Python; scaling it back up smoothly
    // reads as a heavy blur and costs the GPU nothing.
    Image {
        anchors.fill: parent
        source: media.artBlur
        fillMode: Image.PreserveAspectCrop
        smooth: true
        opacity: page.hasBackdrop ? 0.55 : 0
        Behavior on opacity { NumberAnimation { duration: 500 } }
    }
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        opacity: page.hasBackdrop ? 0.35 : 0
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gap

        NowPlaying {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            glass: page.hasBackdrop ? 0.45 : 0
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            spacing: Theme.gap

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                glass: page.hasBackdrop ? 0.45 : 0
                // Spotify: what it plays next (display only). Otherwise the
                // Pi's own music; while the phone plays, tap a song to switch.
                readonly property bool spotifyQueue: media.source === "spotify"
                heading: spotifyQueue ? "Up next on Spotify"
                         : media.source === "phone" ? "Library · tap a song to switch" : "Queue"

                ListView {
                    id: queue
                    anchors { fill: parent; margins: 12; topMargin: 48 }
                    clip: true
                    model: parent.spotifyQueue ? media.upNext : media.queue
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool current: index === media.index

                        width: queue.width
                        height: Theme.touch
                        radius: Theme.radius - 4
                        color: current ? Theme.panelHi : (rowTap.pressed ? Theme.line : "transparent")

                        Item {
                            id: num
                            width: 36
                            height: parent.height
                            anchors { left: parent.left; leftMargin: 12 }
                            Icon {
                                visible: current
                                anchors.verticalCenter: parent.verticalCenter
                                name: "equalizer"
                                size: 22
                                color: Theme.accent
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
                                color: current ? Theme.accent : Theme.text
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
                            onTapped: if (media.source !== "spotify") media.playIndex(index)
                        }
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 108
                glass: page.hasBackdrop ? 0.45 : 0

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                    spacing: 16
                    IconButton { icon: "remove"; size: 64; onClicked: media.volumeDown() }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Label {
                            text: "VOLUME  " + media.volume
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall - 2
                            font.letterSpacing: 2
                        }
                        ProgressBar { Layout.fillWidth: true; height: 10; radius: 5; value: media.volume / 100 }
                    }
                    IconButton { icon: "add"; size: 64; onClicked: media.volumeUp() }
                }
            }
        }
    }
}

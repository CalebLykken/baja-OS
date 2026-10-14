import QtQuick
import QtQuick.Layouts
import "../components"

// The cover as a big framed print on the left. On the right: what's playing
// with the transport keys and volume, and below it what's next. The
// equalizer key opens the EQ over the right-hand column.
Item {
    id: page
    objectName: "musicPage"
    signal navigate(int index)

    property bool eqOpen: false
    onVisibleChanged: if (!visible) eqOpen = false

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gap

        // ---- the cover ----------------------------------------------------
        Card {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.min(height, page.width * 0.46)

            AlbumArt {
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: -4      // centre the print and its shadow
                anchors.verticalCenterOffset: -4
                width: Math.min(parent.width, parent.height) - 56
                height: width
                source: media.artCard
                placeholder: media.source === "phone" ? "phone" : "music"
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.gap
            opacity: page.eqOpen ? 0 : 1
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 180 } }

            // ---- what's playing, transport, volume -------------------------
            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: playing.implicitHeight + 40

                ColumnLayout {
                    id: playing
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        SourceBadge {}
                        Item { Layout.fillWidth: true }
                        IconButton {
                            Layout.topMargin: -6
                            Layout.bottomMargin: -14
                            icon: "equalizer"
                            size: 56
                            onClicked: page.eqOpen = true
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        Layout.topMargin: 2
                        text: media.title
                        font.pixelSize: Theme.fontHero
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
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
                        Layout.topMargin: 14
                        value: media.duration > 0 ? media.position / media.duration : 0
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: page.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        Label { text: page.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                    }

                    Row {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 4
                        spacing: 24
                        IconButton { icon: "previous"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                        IconButton {
                            icon: media.playing ? "pause" : "play"
                            primary: true
                            size: 104
                            onClicked: media.togglePlay()
                        }
                        IconButton { icon: "next"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
                    }

                    // Volume: keys either side of a segmented level.
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 16
                        IconButton { icon: "remove"; size: 60; onClicked: media.volumeDown() }
                        LevelBar {
                            Layout.fillWidth: true
                            value: media.volume / 100
                            onMoved: (v) => media.setVolume(Math.round(v * 100))
                        }
                        Label {
                            Layout.preferredWidth: 40
                            horizontalAlignment: Text.AlignRight
                            text: media.volume
                            font.family: Theme.numFont
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                        }
                        IconButton { icon: "add"; size: 60; onClicked: media.volumeUp() }
                    }
                }
            }

            // ---- what's next -----------------------------------------------
            // Spotify: its queue (display only). Otherwise the Pi's own
            // songs; while the phone plays, tap one to switch to it.
            Card {
                id: listCard
                Layout.fillWidth: true
                Layout.fillHeight: true
                readonly property bool spotifyQueue: media.source === "spotify"
                heading: spotifyQueue ? "Up next on Spotify"
                         : media.source === "phone" ? "Songs on this Pi: tap one to play it here"
                         : "Songs on this Pi"

                ListView {
                    id: queue
                    anchors { fill: parent; margins: 10; topMargin: 44 }
                    clip: true
                    model: listCard.spotifyQueue ? media.upNext : media.queue
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool current: !listCard.spotifyQueue && index === media.index

                        width: queue.width
                        height: 64
                        radius: Theme.radius
                        color: current || rowTap.pressed ? Theme.panelHi : "transparent"

                        Item {
                            id: num
                            width: 44
                            height: parent.height
                            anchors { left: parent.left; leftMargin: 10 }
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
                                font.pixelSize: Theme.fontBody
                                font.weight: current ? Font.DemiBold : Font.Normal
                                elide: Text.ElideRight
                            }
                            Label {
                                width: parent.width
                                text: modelData.artist
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                                elide: Text.ElideRight
                            }
                        }
                        TapHandler {
                            id: rowTap
                            enabled: !listCard.spotifyQueue
                            onTapped: media.playIndex(index)
                        }
                    }
                }

                Label {
                    visible: queue.count === 0
                    anchors { left: parent.left; top: parent.top; leftMargin: 20; topMargin: 56 }
                    text: listCard.spotifyQueue ? "Nothing queued in Spotify" : "No songs in ~/Music on the Pi"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
            }
        }

        // ---- the equalizer, over the right-hand column --------------------
        Card {
            anchors.fill: parent
            heading: "Equalizer"
            opacity: page.eqOpen ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 180 } }

            IconButton {
                anchors { right: parent.right; top: parent.top; margins: 14 }
                icon: "close"
                size: 56
                onClicked: page.eqOpen = false
            }
            EqualizerPanel {
                anchors { fill: parent; margins: 20; topMargin: 84 }
            }
        }
        }
    }
}

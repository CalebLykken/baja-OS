import QtQuick
import QtQuick.Layouts
import "../components"

// Now playing on the left; tappable queue and volume on the right.
Item {
    id: page
    signal navigate(int index)

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gap

        NowPlaying {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            spacing: Theme.gap

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                heading: "Queue"

                ListView {
                    id: queue
                    anchors { fill: parent; margins: 12; topMargin: 48 }
                    clip: true
                    model: media.queue
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property bool current: index === media.index

                        width: queue.width
                        height: Theme.touch
                        radius: Theme.radius - 4
                        color: current ? Theme.panelHi : (rowTap.pressed ? Theme.line : "transparent")

                        Text {
                            id: num
                            width: 36
                            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            text: current ? "▶" : (index + 1)
                            color: current ? Theme.accent : Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                        Column {
                            anchors {
                                left: num.right; right: parent.right; rightMargin: 12
                                verticalCenter: parent.verticalCenter
                            }
                            Text {
                                width: parent.width
                                text: modelData.title
                                color: current ? Theme.accent : Theme.text
                                font.pixelSize: Theme.fontBody - 2
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width
                                text: modelData.artist
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall - 2
                                elide: Text.ElideRight
                            }
                        }
                        TapHandler { id: rowTap; onTapped: media.playIndex(index) }
                    }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 108

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                    spacing: 16
                    IconButton { glyph: "−"; size: 64; onClicked: media.volumeDown() }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text {
                            text: "VOLUME  " + media.volume
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall - 2
                            font.letterSpacing: 2
                        }
                        ProgressBar { Layout.fillWidth: true; height: 10; radius: 5; value: media.volume / 100 }
                    }
                    IconButton { glyph: "+"; size: 64; onClicked: media.volumeUp() }
                }
            }
        }
    }
}

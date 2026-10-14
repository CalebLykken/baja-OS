import QtQuick
import QtQuick.Layouts
import "../components"

// At-a-glance screen: the music card, the maps tile, and the key readouts.
Item {
    id: page
    signal navigate(int index)

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gap

            NowPlaying {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 3
                onOpenMusic: page.navigate(1)
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 2
                tappable: true
                onTapped: page.navigate(2)

                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 20 }
                    spacing: 10
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: "map"
                        color: Theme.textDim
                        size: 64
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "Maps"
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "An offline map of Seattle\nis coming next"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 128
            tappable: true
            onTapped: page.navigate(3)

            RowLayout {
                anchors { fill: parent; margins: 20 }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Boost"
                    value: vehicle.boost.toFixed(1)
                    unit: "psi"
                    warning: vehicle.boost > 15
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Coolant"
                    value: Math.round(vehicle.coolant)
                    unit: "°F"
                    warning: vehicle.coolant > 230
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Battery"
                    value: vehicle.voltage.toFixed(1)
                    unit: "V"
                    warning: vehicle.voltage < 12 || vehicle.voltage > 15
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Speed"
                    value: Math.round(vehicle.speed)
                    unit: "mph"
                }
            }
        }
    }
}

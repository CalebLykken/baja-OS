import QtQuick
import QtQuick.Layouts
import "../components"

// At-a-glance screen: now playing, the maps tile, and three key readouts.
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
                heading: "Maps"
                tappable: true
                onTapped: page.navigate(2)

                Column {
                    anchors.centerIn: parent
                    spacing: 10
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: "navigation"
                        color: Theme.accent
                        size: 64
                    }
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "CarPlay"
                        color: Theme.text
                        font.pixelSize: Theme.fontTitle
                    }
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Connect iPhone to start"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
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
                anchors { fill: parent; leftMargin: 28; rightMargin: 28 }
                Readout {
                    Layout.fillWidth: true
                    label: "Boost"
                    value: vehicle.boost.toFixed(1)
                    unit: "psi"
                    warning: vehicle.boost > 15
                }
                Readout {
                    Layout.fillWidth: true
                    label: "Coolant"
                    value: Math.round(vehicle.coolant)
                    unit: "°F"
                    warning: vehicle.coolant > 230
                }
                Readout {
                    Layout.fillWidth: true
                    label: "Battery"
                    value: vehicle.voltage.toFixed(1)
                    unit: "V"
                    warning: vehicle.voltage < 12 || vehicle.voltage > 15
                }
                Readout {
                    Layout.fillWidth: true
                    label: "Speed"
                    value: Math.round(vehicle.speed)
                    unit: "mph"
                }
            }
        }
    }
}

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

                // Navigating: the next turn, big, and when you'll get there.
                Column {
                    visible: typeof routing !== "undefined" && routing.active
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 24 }
                    spacing: 10
                    Icon {
                        name: routing.maneuverIcon || "straight"
                        size: 72
                        color: Theme.accent
                    }
                    Label {
                        visible: !routing.arrived
                        numeric: true
                        text: Units.distanceText(routing.distanceToTurn)
                        font.pixelSize: Theme.fontHero
                    }
                    Label {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        text: routing.instruction
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "Arrive " + Units.arrivalText(routing.remainingTime) + ", " + Units.distanceText(routing.remainingDistance)
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }

                Column {
                    visible: typeof routing === "undefined" || !routing.active
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
                        text: typeof maps === "undefined" || !maps.ready ? "No map installed yet"
                              : maps.region + "\nworks with no signal"
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
                    value: Units.boost(vehicle.boost).toFixed(Units.boostDecimals)
                    unit: Units.boostUnit
                    warning: vehicle.boost > 15
                }
                Readout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    label: "Coolant"
                    value: Math.round(Units.temp(vehicle.coolant))
                    unit: Units.tempUnit
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
                    value: Math.round(Units.speed(vehicle.speed))
                    unit: Units.speedUnit
                }
            }
        }
    }
}

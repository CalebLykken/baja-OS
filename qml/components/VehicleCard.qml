import QtQuick
import QtQuick.Layouts

// Home screen hero: a render of the Baja with the key readouts under it.
// Tapping it opens the Gauges page.
Card {
    id: vc
    heading: "Baja"
    tappable: true

    ColumnLayout {
        anchors { fill: parent; margins: 20; topMargin: 44 }
        spacing: 8

        Image {
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: Qt.resolvedUrl("../assets/baja-hero.png")
            fillMode: Image.PreserveAspectFit
            // Decode near display size; the render is wider than the card.
            sourceSize.width: 640
            asynchronous: true
            smooth: true
            mipmap: true
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            rowSpacing: 10
            columnSpacing: 16
            Readout {
                Layout.fillWidth: true
                label: "Boost"
                value: vehicle.boost.toFixed(1)
                unit: "psi"
                warning: vehicle.boost > 15
            }
            Readout {
                Layout.fillWidth: true
                label: "Speed"
                value: Math.round(vehicle.speed)
                unit: "mph"
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
        }
    }
}

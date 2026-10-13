import QtQuick
import QtQuick.Layouts
import "../components"

// Six live gauges in a 3x2 grid. Warning thresholds turn a gauge red.
Item {
    id: page
    signal navigate(int index)

    GridLayout {
        anchors.fill: parent
        columns: 3
        rowSpacing: Theme.gap
        columnSpacing: Theme.gap

        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "RPM"; unit: "rpm"
            value: vehicle.rpm; minValue: 0; maxValue: 7000; warnAbove: 6000
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Speed  ·  gear " + vehicle.gear; unit: "mph"
            value: vehicle.speed; minValue: 0; maxValue: 120
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Boost"; unit: "psi"; decimals: 1
            value: vehicle.boost; minValue: -20; maxValue: 20; warnAbove: 15
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Coolant"; unit: "°F"
            value: vehicle.coolant; minValue: 100; maxValue: 260; warnAbove: 230
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Intake"; unit: "°F"
            value: vehicle.intake; minValue: 0; maxValue: 200; warnAbove: 150
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Battery"; unit: "V"; decimals: 1
            value: vehicle.voltage; minValue: 10; maxValue: 16; warnAbove: 15; warnBelow: 12
        }
    }
}

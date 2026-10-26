import QtQuick
import QtQuick.Layouts
import "../components"

// Six live gauges in a 3x2 grid. Warning thresholds (vehicle.limits, from
// backend/vehicle.py) turn a gauge red.
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
            value: vehicle.rpm; minValue: 0; maxValue: 7000; warnAbove: vehicle.limits.rpmHigh
            labelDivisor: 1000
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Speed  ·  gear " + (vehicle.gear || "N"); unit: Units.speedUnit
            value: Units.speed(vehicle.speed); minValue: 0; maxValue: Units.metric ? 200 : 120
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Boost"; unit: Units.boostUnit; decimals: Units.boostDecimals
            value: Units.boost(vehicle.boost); minValue: Units.boost(-20); maxValue: Units.boost(20)
            warnAbove: Units.boost(vehicle.limits.boostHigh)
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Coolant"; unit: Units.tempUnit
            value: Units.temp(vehicle.coolant); minValue: Units.temp(100); maxValue: Units.temp(260)
            warnAbove: Units.temp(vehicle.limits.coolantHigh)
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Intake"; unit: Units.tempUnit
            value: Units.temp(vehicle.intake); minValue: Units.temp(0); maxValue: Units.temp(200)
            warnAbove: Units.temp(vehicle.limits.intakeHigh)
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Battery"; unit: "V"; decimals: 1
            value: vehicle.voltage; minValue: 10; maxValue: 16
            warnAbove: vehicle.limits.voltageHigh; warnBelow: vehicle.limits.voltageLow
        }
    }
}

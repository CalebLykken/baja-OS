import QtQuick
import QtQuick.Layouts
import "../components"

// Six live gauges in a 3x2 grid. Warning thresholds (vehicle.limits, from
// backend/vehicle.py) turn a gauge red. A reading that isn't known (the car
// isn't answering) shows a dash instead of a number; the speed is also known
// from the GPS. RPM, speed and boost hold a peak tell-tale marker (see
// Gauge.qml); tap one of those gauges to clear its peak. While the car
// reports trouble codes (vehicle.codes), a strip under the grid lists each
// with its description.
Item {
    id: page
    signal navigate(int index)

    // The last launch to 60 mph (100 km/h), 0 until the truck has done one.
    readonly property real launch: Units.metric ? vehicle.zeroToHundred : vehicle.zeroToSixty

    // The gauges sweep once, the first time this page is shown.
    property bool testedOnce: false
    function maybeTest() {
        if (visible && !testedOnce) {
            testedOnce = true
            startTest.start()
        }
    }
    onVisibleChanged: maybeTest()
    Component.onCompleted: maybeTest()
    Timer {
        id: startTest
        interval: 100       // let the grid lay out first
        onTriggered: {
            for (var i = 0; i < grid.children.length; i++)
                if (grid.children[i].selfTest)
                    grid.children[i].selfTest()
        }
    }

    Rectangle {
        id: strip
        readonly property bool shown: vehicle.codes.length > 0
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: shown ? list.implicitHeight + 16 : 0
        visible: shown
        radius: Theme.radius
        color: Theme.panel
        border { width: Theme.border; color: Theme.warn }

        Column {
            id: list
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
            spacing: 2
            Repeater {
                model: vehicle.codes.slice(0, 4)
                Row {
                    spacing: 12
                    Label {
                        text: modelData.code
                        numeric: true
                        color: Theme.warn
                        font.pixelSize: Theme.fontSmall
                        font.weight: Font.DemiBold
                    }
                    Label {
                        width: list.width - x - 12
                        text: (modelData.text || "") + (modelData.pending ? (modelData.text ? "  ·  " : "") + "pending" : "")
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                        elide: Text.ElideRight
                    }
                }
            }
            Label {
                visible: vehicle.codes.length > 4
                text: "+" + (vehicle.codes.length - 4) + " more"
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }
    }

    GridLayout {
        id: grid
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.bottom: strip.shown ? strip.top : parent.bottom
        anchors.bottomMargin: strip.shown ? Theme.gap : 0
        columns: 3
        rowSpacing: Theme.gap
        columnSpacing: Theme.gap

        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "RPM"; unit: "rpm"
            known: vehicle.engineKnown
            value: vehicle.rpm; minValue: 0; maxValue: 7000; warnAbove: vehicle.limits.rpmHigh
            labelDivisor: 1000
            peakHold: true
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Speed  ·  gear " + (vehicle.engineKnown ? vehicle.gear || "N" : "—")
                   + (page.launch > 0 ? "  ·  0-" + (Units.metric ? "100 " : "60 ") + page.launch.toFixed(1) + " s" : "")
            unit: Units.speedUnit
            known: vehicle.speedKnown
            value: Units.speed(vehicle.speed); minValue: 0; maxValue: Units.metric ? 200 : 120
            peakHold: true
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Boost"; unit: Units.boostUnit; decimals: Units.boostDecimals
            known: vehicle.engineKnown
            value: Units.boost(vehicle.boost); minValue: Units.boost(-20); maxValue: Units.boost(20)
            warnAbove: Units.boost(vehicle.limits.boostHigh)
            peakHold: true
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Coolant"; unit: Units.tempUnit
            known: vehicle.engineKnown
            value: Units.temp(vehicle.coolant); minValue: Units.temp(100); maxValue: Units.temp(260)
            warnAbove: Units.temp(vehicle.limits.coolantHigh)
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Intake"; unit: Units.tempUnit
            known: vehicle.engineKnown
            value: Units.temp(vehicle.intake); minValue: Units.temp(0); maxValue: Units.temp(200)
            warnAbove: Units.temp(vehicle.limits.intakeHigh)
        }
        Gauge {
            Layout.fillWidth: true; Layout.fillHeight: true
            label: "Battery"; unit: "V"; decimals: 1
            known: vehicle.voltageKnown
            value: vehicle.voltage; minValue: 10; maxValue: 16
            warnAbove: vehicle.limits.voltageHigh; warnBelow: vehicle.limits.voltageLow
        }
    }
}

import QtQuick

// An engine warning chip: shown while a reading from the car is out of
// range (vehicle.warnings: overheating, battery voltage, overboost), never
// from the simulated data. With more than one, they take turns.
Rectangle {
    id: chip
    signal tapped()

    readonly property var warnings: typeof vehicle !== "undefined" ? vehicle.warnings : []
    property int turn: 0
    readonly property string current: warnings.length ? warnings[turn % warnings.length] : ""
    property string shown: ""                 // kept while it fades out
    onCurrentChanged: if (current !== "") shown = current

    width: 96
    height: column.implicitHeight + 14
    radius: Theme.radius
    color: tap.pressed ? Qt.darker(Theme.warn, 1.2) : Theme.warn
    opacity: current !== "" ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Timer {
        interval: 2500; repeat: true
        running: chip.warnings.length > 1
        onTriggered: chip.turn++
    }

    Column {
        id: column
        anchors.centerIn: parent
        spacing: 2
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: chip.shown === "coolant" ? "thermostat" : chip.shown === "voltage" ? "battery_alert" : "speed"
            size: 28
            color: Theme.bg
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 3
            Label {
                id: value
                numeric: true
                color: Theme.bg
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
                text: chip.shown === "coolant" ? Math.round(Units.temp(vehicle.coolant))
                      : chip.shown === "voltage" ? vehicle.voltage.toFixed(1)
                      : chip.shown === "boost" ? Units.boost(vehicle.boost).toFixed(Units.boostDecimals)
                      : ""
            }
            Label {
                anchors.baseline: value.baseline
                color: Theme.bg
                font.pixelSize: Theme.fontLegend
                text: chip.shown === "coolant" ? Units.tempUnit
                      : chip.shown === "voltage" ? "V"
                      : chip.shown === "boost" ? Units.boostUnit
                      : ""
            }
        }
    }

    TapHandler { id: tap; onTapped: chip.tapped() }
}

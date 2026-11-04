import QtQuick

// An engine warning chip: shown while a reading from the car is out of
// range or its check-engine lamp is on (vehicle.warnings: overheating, battery voltage, overboost, and the
// check-engine lamp), never
// from the simulated data. With more than one, they take turns.
Rectangle {
    id: chip
    signal tapped()

    readonly property var warnings: typeof vehicle !== "undefined" ? vehicle.warnings : []
    property int turn: 0
    readonly property string current: warnings.length ? warnings[turn % warnings.length] : ""
    property string shown: ""                 // kept while it fades out
    property bool wasShowing: false           // was a warning on screen before this change?
    onCurrentChanged: {
        if (current === "") {
            wasShowing = false
            return
        }
        if (wasShowing) {
            swapShown.restart()               // another warning while on screen: crossfade, don't pop
        } else {
            swapShown.stop()
            column.opacity = 1
            shown = current
            arrive.restart()                  // the chip appears: one nudge
        }
        wasShowing = true
    }

    width: 96
    height: column.implicitHeight + 14
    radius: Theme.radius
    color: tap.pressed ? Qt.darker(Theme.warn, 1.2) : Theme.warn
    opacity: current !== "" ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    SequentialAnimation {
        id: arrive
        NumberAnimation { target: chip; property: "scale"; from: 0.85; to: 1.08; duration: 160; easing.type: Easing.OutCubic }
        NumberAnimation { target: chip; property: "scale"; to: 1.0; duration: 140; easing.type: Easing.InOutQuad }
    }

    // The icon and value dip out and back in, swapping at the bottom of the dip.
    SequentialAnimation {
        id: swapShown
        NumberAnimation { target: column; property: "opacity"; to: 0.3; duration: 120 }
        ScriptAction { script: { if (chip.current !== "") chip.shown = chip.current } }
        NumberAnimation { target: column; property: "opacity"; to: 1; duration: 120 }
    }

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
            name: chip.shown === "coolant" ? "thermostat" : chip.shown === "voltage" ? "battery_alert" : chip.shown === "mil" ? "engine_check" : "speed"
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
                      : chip.shown === "mil" ? "CHECK"
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

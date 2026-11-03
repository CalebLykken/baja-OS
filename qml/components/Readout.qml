import QtQuick

// Compact numeric readout: a legend on top, a big value with its unit below.
Column {
    id: r
    property string label
    property string value
    property string unit
    property bool warning: false

    SequentialAnimation {
        id: pulse
        NumberAnimation { target: num; property: "scale"; to: 1.12; duration: 110; easing.type: Easing.OutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.0; duration: 140; easing.type: Easing.InOutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.12; duration: 110; easing.type: Easing.OutQuad }
        NumberAnimation { target: num; property: "scale"; to: 1.0; duration: 160; easing.type: Easing.InOutQuad }
    }

    spacing: 2

    // When a value crosses into its warning state, the numeral eases to Ember
    // and pulses twice, then holds still. The pulse is one-shot on purpose: it
    // fires only on the false-to-true edge and never loops, so a driver's eye is
    // caught once and the Pi is not asked to render a continuous animation.
    // Scale leaves the layout size alone, so the unit label does not move.
    onWarningChanged: {
        if (warning) pulse.restart();
        else { pulse.stop(); num.scale = 1 }
    }

    Legend { text: r.label }
    Row {
        spacing: 6
        Label {
            id: num
            numeric: true
            text: r.value
            color: r.warning ? Theme.warn : Theme.text
            font.pixelSize: Theme.fontReadout
            font.weight: Theme.numWeight
            transformOrigin: Item.Left
            Behavior on color { ColorAnimation { duration: 180 } }
        }
        Label {
            text: r.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            anchors.baseline: num.baseline
        }
    }
}

import QtQuick

// Compact numeric readout: a legend on top, a big value with its unit below.
Column {
    id: r
    property string label
    property string value
    property string unit
    property bool warning: false

    spacing: 2

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
        }
        Label {
            text: r.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            anchors.baseline: num.baseline
        }
    }
}

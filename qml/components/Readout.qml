import QtQuick

// Compact numeric readout: label on top, big value with unit below.
Column {
    id: r
    property string label
    property string value
    property string unit
    property bool warning: false

    spacing: 2

    Label {
        text: r.label.toUpperCase()
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall - 3
        font.letterSpacing: 1.5
    }
    Row {
        spacing: 4
        Label {
            numeric: true
            text: r.value
            color: r.warning ? Theme.warn : Theme.text
            font.pixelSize: 40
            font.weight: Theme.numWeight
        }
        Label {
            text: r.unit
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            anchors.baseline: parent.children[0].baseline
        }
    }
}

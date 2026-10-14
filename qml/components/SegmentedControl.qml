import QtQuick

// One joined control for picking one of a few options (Style, Units). The
// selected segment is filled with the accent, so "selected" never looks like
// a standalone action key.
Rectangle {
    id: ctl
    property var options: []        // [{ label, value }]
    property var current
    signal picked(var value)

    implicitWidth: row.implicitWidth + 2 * Theme.border
    height: 56
    radius: Theme.radius
    color: Theme.panelHi
    border.width: Theme.border
    border.color: Theme.line

    Row {
        id: row
        anchors { fill: parent; margins: Theme.border }
        Repeater {
            model: ctl.options
            Rectangle {
                readonly property bool selected: modelData.value === ctl.current
                width: label.implicitWidth + 40
                height: row.height
                radius: Math.max(0, Theme.radius - Theme.border)
                color: selected ? Theme.accent : (tap.pressed ? Theme.line : "transparent")

                // Divider between unselected neighbours.
                Rectangle {
                    visible: index > 0 && !parent.selected
                             && ctl.options[index - 1].value !== ctl.current
                    width: Theme.border
                    height: parent.height * 0.5
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    color: Theme.line
                }
                Label {
                    id: label
                    anchors.centerIn: parent
                    text: modelData.label
                    color: parent.selected ? Theme.bg : Theme.text
                    font.pixelSize: Theme.fontBody - 2
                    font.weight: parent.selected ? Font.DemiBold : Font.Normal
                }
                TapHandler { id: tap; onTapped: ctl.picked(modelData.value) }
            }
        }
    }
}

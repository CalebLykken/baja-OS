import QtQuick

// One joined control for picking one of a few options (Style, Units). The
// selected segment is filled with the accent, so "selected" never looks like
// a standalone action key. The fill is one slider that glides to the new choice.
Rectangle {
    id: ctl
    property var options: []        // [{ label, value }]
    property var current
    property bool stretch: false    // segments share the full width (tabs)
    signal picked(var value)

    readonly property int selIndex: {
        for (let i = 0; i < options.length; i++)
            if (options[i].value === current) return i
        return -1
    }
    // The slider only animates after the first placement, so a page opens
    // with the control already on its selection.
    property bool ready: false
    Component.onCompleted: Qt.callLater(function() { ctl.ready = true })

    implicitWidth: row.implicitWidth + 2 * Theme.border
    height: 56
    radius: Theme.radius
    color: Theme.panelHi
    border.width: Theme.border
    border.color: Theme.line

    // Same box as the row, so the slider shares its coordinates; declared first
    // so it paints under the labels.
    Item {
        anchors { fill: parent; margins: Theme.border }
        Rectangle {
            id: slider
            readonly property Item seg: { segs.count; return ctl.selIndex >= 0 ? segs.itemAt(ctl.selIndex) : null }
            visible: seg !== null
            x: seg ? seg.x : 0
            width: seg ? seg.width : 0
            height: row.height
            radius: Math.max(0, Theme.radius - Theme.border)
            color: Theme.accent
            Behavior on x { enabled: ctl.ready; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            Behavior on width { enabled: ctl.ready; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        }
    }

    Row {
        id: row
        anchors { fill: parent; margins: Theme.border }
        Repeater {
            id: segs
            model: ctl.options
            Rectangle {
                readonly property bool selected: modelData.value === ctl.current
                width: ctl.stretch ? row.width / Math.max(1, ctl.options.length)
                                   : label.implicitWidth + 40
                height: row.height
                radius: Math.max(0, Theme.radius - Theme.border)
                color: !selected && tap.pressed ? Theme.line : "transparent"

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
                    Behavior on color { ColorAnimation { duration: 150 } }
                    font.pixelSize: Theme.fontBody - 2
                    font.weight: parent.selected ? Font.DemiBold : Font.Normal
                }
                TapHandler { id: tap; onTapped: ctl.picked(modelData.value) }
            }
        }
    }
}

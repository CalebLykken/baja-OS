import QtQuick

// What a list or grid says when it has nothing to show: an icon, a line saying
// what is missing and a hint saying how to fill it, centred in the space.
// alignTop pins it to the top instead of centring it, for a list whose lower
// part something else covers (the on-screen keyboard). Static (no animation,
// no timers) and takes no taps, so a list under it keeps working. Size it to the list: inside a Flickable, parent is the
// content item, so use width/height rather than anchors.fill.
Item {
    id: root
    property string icon: ""
    property string title: ""
    property string hint: ""
    property color iconColor: Theme.textDim
    property bool alignTop: false
    readonly property real contentY: block.y
    readonly property bool hintShown: hintLabel.visible

    Column {
        id: block
        x: (root.width - width) / 2
        y: root.alignTop ? 12 : (root.height - height) / 2
        width: Math.min(root.width - 40, 720)
        spacing: 10
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: root.icon
            color: root.iconColor
            size: 72
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.title
            font.pixelSize: Theme.fontTitle
            font.weight: Font.DemiBold
        }
        Label {
            id: hintLabel
            visible: root.hint !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.hint
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
    }
}

import QtQuick
import ".."

// A static preview of one Style in its own colours, shape, numerals and name,
// following day/night. Plain rectangles and text only: nothing moves, nothing
// polls. Tapping it picks the style.
Rectangle {
    id: tile
    property string styleName: "amber"
    readonly property var t: Theme.dark ? Theme.styles[styleName]
        : Object.assign({}, Theme.styles[styleName], Theme.lightStyles[styleName] || {})
    readonly property bool picked: styleName === Theme.style
    readonly property string title: Theme.styleTitles[styleName] || styleName
    objectName: "tile_" + styleName
    Accessible.role: Accessible.Button
    Accessible.name: title + " style"
    width: 148
    height: 112
    color: tap.pressed ? t.panelHi : t.bg
    radius: t.radius
    border.width: t.border
    border.color: t.line

    // The selected ring, around the tile.
    Rectangle {
        objectName: "ring"
        visible: tile.picked
        anchors.fill: parent
        anchors.margins: -4
        z: -1
        color: "transparent"
        radius: tile.t.radius + 4
        border.width: 3
        border.color: Theme.accent
    }
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 }
        height: 60
        color: tile.t.panel
        radius: tile.t.radius
        border.width: tile.t.border
        border.color: tile.t.line
        Rectangle {
            width: 4
            radius: 2
            color: tile.t.accent
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 8 }
        }
        Text {
            anchors.centerIn: parent
            text: "88"
            color: tile.t.text
            font.family: tile.t.numFont
            font.italic: tile.t.numItalic
            font.weight: tile.t.numWeight
            font.pixelSize: 36
        }
        Rectangle {
            width: 10; height: 10; radius: 5
            color: tile.t.ok
            anchors { right: parent.right; top: parent.top; margins: 8 }
        }
    }
    Text {
        objectName: "title"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 8 }
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: tile.title
        color: tile.t.text
        font.family: tile.t.font
        font.pixelSize: 20
        font.weight: Font.DemiBold
    }
    TapHandler {
        id: tap
        onTapped: Theme.style = tile.styleName
    }
}

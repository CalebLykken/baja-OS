import QtQuick
import QtQuick.Layouts

// A modal dialog over a dimmed scrim: the update notice, the pairing request
// and the key-off countdown all use it. Fill the parent with it, set `shown`
// and `title`, and put the body and buttons inside; they go into a column on
// the card. It fades in over 200 ms and the card settles from 0.96 to full
// size. Hidden (and free) when `shown` is false. Taps never reach the page
// underneath.
Rectangle {
    id: prompt
    property bool shown: false
    property string title: ""
    default property alias content: column.data

    color: Qt.rgba(0, 0, 0, 0.6)
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200 } }
    MouseArea { objectName: "swallow"; anchors.fill: parent }   // nothing underneath while it's up

    Item {
        objectName: "promptCard"
        anchors.centerIn: parent
        width: 720
        height: column.implicitHeight + 64
        scale: prompt.shown ? 1 : 0.96
        Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

        Card {
            anchors.fill: parent
            ColumnLayout {
                id: column
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 }
                spacing: 12
                Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    textFormat: Text.PlainText      // titles can carry a name from another device
                    text: prompt.title
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
            }
        }
    }
}

import QtQuick
import "../components"

// Placeholder for CarPlay. The Carlinkit dongle's video will render here.
Item {
    id: page
    signal navigate(int index)

    Card {
        anchors.fill: parent

        Column {
            anchors.centerIn: parent
            spacing: 14
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "navigation"
                color: Theme.accent
                size: 108
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "CarPlay not connected"
                color: Theme.text
                font.pixelSize: Theme.fontTitle
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Plug in the Carlinkit adapter and your iPhone"
                color: Theme.textDim
                font.pixelSize: Theme.fontBody
            }
        }
    }
}

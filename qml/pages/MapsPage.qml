import QtQuick
import "../components"

// Placeholder until the offline map lands (docs/ROADMAP.md).
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
                name: "map"
                color: Theme.textDim
                size: 108
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "The offline map is coming next"
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Seattle first, working without signal, then GPS and directions"
                color: Theme.textDim
                font.pixelSize: Theme.fontBody
            }
        }
    }
}

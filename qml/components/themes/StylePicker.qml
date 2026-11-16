import QtQuick
import ".."

// The Style setting: a heading with the picked name, then a wrapping grid of
// preview tiles, so ten styles are as easy as five. Static: nothing moves.
Column {
    id: picker
    property var model: Theme.styleNames
    spacing: Theme.gap

    Row {
        spacing: Theme.gap
        Label {
            text: "Style"
            font.pixelSize: Theme.fontBody
        }
        Label {
            objectName: "pickedTitle"
            text: Theme.styleTitles[Theme.style] || Theme.style
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
    }
    Flow {
        width: parent.width
        spacing: Theme.gap
        Repeater {
            model: picker.model
            StyleTile { styleName: modelData }
        }
    }
}

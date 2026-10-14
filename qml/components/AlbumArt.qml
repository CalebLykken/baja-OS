import QtQuick

// The album cover as a framed print sitting on the card: square, the style's
// radius and border, and a hard offset shadow like a decal on a map. Matte,
// no glow (docs/DESIGN.md). The cover arrives pre-cropped with rounded
// corners from Python (media.artCard), since QML can't round an image's
// corners without the effects module. With no cover, a quiet tile with an
// icon stands in.
Item {
    id: root
    property string source                 // rounded cover (media.artCard)
    property string placeholder: "music"   // Icon name when there's no cover

    readonly property bool hasArt: cover.status === Image.Ready

    // Hard offset shadow.
    Rectangle {
        x: 6; y: 8
        width: parent.width; height: parent.height
        radius: Theme.radius
        color: Qt.darker(Theme.bg, 1.8)
        opacity: 0.7
    }

    // No cover: a quiet tile, not an accent.
    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.panelHi
        visible: !root.hasArt
        Icon {
            anchors.centerIn: parent
            name: root.placeholder
            color: Theme.textDim
            size: parent.width * 0.4
        }
    }

    Image {
        id: cover
        anchors.fill: parent
        source: root.source
        fillMode: Image.PreserveAspectFit
        sourceSize { width: 600; height: 600 }
        asynchronous: true
        smooth: true
        mipmap: true
    }

    // The frame.
    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: "transparent"
        border.width: Theme.border
        border.color: Theme.line
    }
}

import QtQuick

// Album art with rounded corners and a soft glow in the cover's own colours.
//
// Both images are prepared in Python (backend/hub.py) when the cover
// changes: `source` is the cover cropped square with rounded corners
// (media.artCard), `glowSource` is a soft, edge-faded halo of it
// (media.artGlow) drawn larger behind. QML can't round or feather an image
// without the effects module, so baking them keeps this to two plain
// Images. With no cover, it shows a placeholder icon.
Item {
    id: root
    property string source                 // rounded cover (media.artCard)
    property string glowSource             // soft halo (media.artGlow)
    property string placeholder: "music"   // Icon name when there's no cover

    readonly property bool hasArt: cover.status === Image.Ready

    Image {
        anchors.centerIn: parent
        width: parent.width * 1.45
        height: parent.height * 1.45
        source: root.glowSource
        fillMode: Image.PreserveAspectCrop
        smooth: true
        opacity: root.hasArt && root.glowSource !== "" ? 0.55 : 0
        Behavior on opacity { NumberAnimation { duration: 400 } }
    }

    Rectangle {
        anchors.fill: parent
        radius: width * 0.06
        color: Theme.accentDim
        visible: !root.hasArt
        Icon {
            anchors.centerIn: parent
            name: root.placeholder
            color: Theme.accent
            size: parent.width * 0.42
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
        // A gentle scale-in when a new cover arrives.
        onStatusChanged: if (status === Image.Ready) bump.restart()
        NumberAnimation on scale {
            id: bump
            running: false
            from: 0.94; to: 1.0
            duration: 380
            easing.type: Easing.OutBack
        }
    }
}

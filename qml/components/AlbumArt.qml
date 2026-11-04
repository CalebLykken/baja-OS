import QtQuick

// The album cover as a framed print sitting on the card: square, the style's
// radius and border, and a hard offset shadow like a decal on a map. Matte,
// no glow (docs/DESIGN.md). The cover arrives pre-cropped with rounded
// corners from Python (media.artCard), since QML can't round an image's
// corners without the effects module. With no cover, a quiet tile with an
// icon stands in.
//
// A track change crossfades: the new cover loads into the hidden one of two
// Images and fades in over the old one (which stays opaque underneath, so
// there is no dip), then the old one is emptied to free its texture. The
// tile only shows when there is genuinely no cover. The incoming cover also
// settles like a print dropped onto the card: it grows from 94% to full size
// (a small overshoot) during the same 250 ms. That is a one-shot transform on
// an existing texture, skipped when the card isn't visible, and nothing runs
// once it ends.
Item {
    id: root
    property string source                 // rounded cover (media.artCard)
    property string placeholder: "music"   // Icon name when there's no cover

    readonly property bool hasArt: (front.status === Image.Ready && front.opacity > 0)
                                   || (back.status === Image.Ready && back.opacity > 0)

    // Two covers, swapping roles after each fade.
    property bool aFront: true
    readonly property var front: aFront ? imgA : imgB
    readonly property var back: aFront ? imgB : imgA
    property string target: ""        // newest source asked for
    property bool pending: false      // back is loading the target
    property bool wantTile: false     // no cover (or it failed): show the tile
    readonly property real frontScale: front.scale
    readonly property bool fadeRunning: fadeIn.running
    readonly property bool frontShown: front.status === Image.Ready && front.opacity > 0

    function apply(src) {
        if (src === target)
            return
        target = src
        pending = false
        fadeIn.stop()
        fadeOut.stop()
        imgA.scale = 1
        imgB.scale = 1
        back.opacity = 0
        back.source = ""
        if (src === "") {
            // Fade the old cover away over the tile.
            wantTile = true
            if (front.source != "") {
                fadeOut.target = front
                fadeOut.start()
            }
            return
        }
        wantTile = false
        if (front.source == src) {
            // Back to the cover that is still showing (or just fading out).
            front.opacity = 1
            front.scale = 1
            return
        }
        pending = true
        back.source = src
        settle()
    }

    // Called whenever the hidden image's status changes.
    function settle() {
        if (!pending)
            return
        if (back.status === Image.Ready) {
            pending = false
            if (!root.visible) {
                // Nobody can see it: swap at once.
                back.opacity = 1
                back.scale = 1
                retire()
                return
            }
            fadeIn.incoming = back
            fadeIn.start()
        } else if (back.status === Image.Error) {
            // Honest fallback: no cover, show the tile.
            pending = false
            back.source = ""
            wantTile = true
            if (front.source != "") {
                fadeOut.target = front
                fadeOut.start()
            }
        }
    }

    onSourceChanged: apply(source)
    Component.onCompleted: apply(source)

    // The new cover is fully opaque and full size: retire the old one.
    function retire() {
        var old = root.front
        root.aFront = !root.aFront
        old.source = ""
        old.opacity = 0
        old.scale = 1
        root.front.scale = 1
    }

    ParallelAnimation {
        id: fadeIn
        property var incoming: null
        NumberAnimation {
            target: fadeIn.incoming; property: "opacity"; from: 0; to: 1
            duration: 250; easing.type: Easing.InOutQuad
        }
        NumberAnimation {
            target: fadeIn.incoming; property: "scale"; from: 0.94; to: 1.0
            duration: 250; easing.type: Easing.OutBack
        }
        onFinished: root.retire()
    }

    NumberAnimation {
        id: fadeOut
        property: "opacity"; to: 0
        duration: 250; easing.type: Easing.InOutQuad
        onFinished: {
            root.front.source = ""
            root.front.opacity = 0
        }
    }

    // Hard offset shadow.
    Rectangle {
        x: 6; y: 8
        width: parent.width; height: parent.height
        radius: Theme.radius
        color: Qt.darker(Theme.bg, 1.8)
        opacity: 0.7
    }

    // No cover: a quiet tile, not an accent. Stays under a cover that is
    // fading in or out.
    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.panelHi
        visible: root.wantTile || !root.frontShown
        Icon {
            anchors.centerIn: parent
            name: root.placeholder
            color: Theme.textDim
            size: parent.width * 0.4
        }
    }

    Image {
        id: imgA
        anchors.fill: parent
        z: root.aFront ? 0 : 1
        fillMode: Image.PreserveAspectFit
        sourceSize { width: 600; height: 600 }
        asynchronous: true
        smooth: true
        mipmap: true
        opacity: 1
        onStatusChanged: if (!root.aFront) root.settle()
    }

    Image {
        id: imgB
        anchors.fill: parent
        z: root.aFront ? 1 : 0
        fillMode: Image.PreserveAspectFit
        sourceSize { width: 600; height: 600 }
        asynchronous: true
        smooth: true
        mipmap: true
        opacity: 0
        onStatusChanged: if (root.aFront) root.settle()
    }

    // The frame.
    Rectangle {
        anchors.fill: parent
        z: 2
        radius: Theme.radius
        color: "transparent"
        border.width: Theme.border
        border.color: Theme.line
    }
}

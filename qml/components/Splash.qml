import QtQuick

// Startup splash: the Baja's side profile sits in the dark, its headlight
// comes on, then the name, then the whole thing fades into the dashboard.
// Tap to skip. At boot the Plymouth theme in deploy/plymouth has already been
// showing the same truck at the same spot on the same background, so this
// picks up seamlessly; keep the two in sync if either moves. Only opacity
// animates, which the Pi 2's GPU handles easily; the glow is painted once.
Rectangle {
    id: splash
    color: "#050506"   // matches the Plymouth boot screen, whatever the style
    z: 100

    // Where the headlight sits in baja-side.png (0..1 of the image), from
    // the Blender render script.
    readonly property real headX: 0.0659
    readonly property real headY: 0.5864

    signal finished()

    function finish() {
        if (!fadeOut.running && visible) fadeOut.start()
    }

    Item {
        id: stage
        width: Math.min(parent.width * 0.78, 1000)
        height: width * 525 / 1429
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -30

        Image {
            id: truck
            anchors.fill: parent
            source: Qt.resolvedUrl("../assets/baja-side.png")
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 1000
            smooth: true
            mipmap: true
        }

        // Headlight: a warm glow on the lens plus a soft beam reaching
        // forward (left, since the truck faces left).
        Canvas {
            id: glow
            width: stage.width * 0.5
            height: stage.height * 0.6
            x: stage.width * splash.headX - width * 0.9
            y: stage.height * splash.headY - height / 2
            opacity: 0
            onWidthChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var cx = width * 0.9, cy = height / 2
                // Canvas has no blur, so feather the beam by stacking faint
                // wedges that widen outward; the edges fade on their own.
                ctx.globalCompositeOperation = "lighter"
                for (var i = 0; i < 7; i++) {
                    var spread = 0.10 + i * 0.05
                    var beam = ctx.createLinearGradient(cx, 0, 0, 0)
                    beam.addColorStop(0, "rgba(255, 236, 200, 0.09)")
                    beam.addColorStop(1, "rgba(255, 236, 200, 0)")
                    ctx.fillStyle = beam
                    ctx.beginPath()
                    ctx.moveTo(cx, cy - height * 0.03)
                    ctx.lineTo(0, cy - height * spread * 0.8)
                    ctx.lineTo(0, cy + height * spread)
                    ctx.lineTo(cx, cy + height * 0.04)
                    ctx.closePath()
                    ctx.fill()
                }
                var r = height * 0.32
                var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r)
                g.addColorStop(0, "rgba(255, 250, 235, 1)")
                g.addColorStop(0.25, "rgba(255, 236, 200, 0.7)")
                g.addColorStop(1, "rgba(255, 220, 170, 0)")
                ctx.fillStyle = g
                ctx.beginPath()
                ctx.arc(cx, cy, r, 0, Math.PI * 2)
                ctx.fill()
            }
        }
    }

    Column {
        id: title
        anchors { horizontalCenter: parent.horizontalCenter; top: stage.bottom; topMargin: 28 }
        spacing: 6
        opacity: 0
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "BAJA OS"
            numeric: true
            font.pixelSize: 44
            font.weight: Theme.numWeight
            font.letterSpacing: 10
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 120; height: 3; radius: 1.5
            color: Theme.accent
        }
    }

    SequentialAnimation {
        running: true
        PauseAnimation { duration: 300 }
        // Headlight flicks on: a quick blip, then full.
        NumberAnimation { target: glow; property: "opacity"; to: 0.6; duration: 90 }
        NumberAnimation { target: glow; property: "opacity"; to: 0.15; duration: 110 }
        NumberAnimation { target: glow; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutQuad }
        NumberAnimation { target: title; property: "opacity"; to: 1; duration: 500 }
        PauseAnimation { duration: 1100 }
        ScriptAction { script: splash.finish() }
    }

    NumberAnimation {
        id: fadeOut
        target: splash
        property: "opacity"
        to: 0
        duration: 450
        easing.type: Easing.InQuad
        onFinished: { splash.visible = false; splash.finished() }
    }

    TapHandler { onTapped: splash.finish() }
}

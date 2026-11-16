import QtQuick

// Startup splash: the Baja in Atlantic Blue, three-quarters from the front,
// sits in the dark with the boot screen's loading bar still sweeping under
// it. Once the dashboard is up the bar fills and fades, the headlights come
// on, then the name, then a short greeting that suits the time of day, the
// weekday and the date (a holiday, a weekend line, or one of three phrasings
// for the time slot, picked by day; a plain line until the clock is known to
// be set), then the whole thing fades into the dashboard. The text uses the
// dark colour set whatever the day or night appearance, since the ground is
// fixed. Tap to skip.
//
// At boot the Plymouth theme in deploy/plymouth has already been showing the
// same truck and bar at the same spot on the same background, so this picks
// up seamlessly; keep the two in sync if either moves (truck 70% of the width,
// max 900, 40 px above centre; a 4 px bar 56 px below it). Only opacity and
// one bar position animate, which the Pi's GPU handles easily; the glow is
// painted once.
Rectangle {
    id: splash
    color: "#050506"   // matches the Plymouth boot screen, whatever the style
    z: 100

    // baja-boot.png's size, and where its headlights sit (0..1 of the image),
    // from tools/render_boot.py's baja-boot.json.
    readonly property real imageW: 1259
    readonly property real imageH: 690
    readonly property point nearHead: Qt.point(0.3052, 0.6312)
    readonly property point farHead: Qt.point(0.0437, 0.547)

    signal finished()

    function finish() {
        if (!fadeOut.running && visible) fadeOut.start()
    }

    // Plain JS on a Date, so it cannot fail at start-up. Fixed dates win, then
    // the weekend lines, then the time slot; each slot has three phrasings, and
    // the day of the year picks one, so it changes daily and holds all day.
    // `synced` is whether the clock has been set: with no RTC battery the
    // clock at boot is fake-hwclock's last save, the end of the previous
    // drive, so until chrony has set it the date and hour mean nothing and
    // the line is a plain one.
    function greeting(d, synced) {
        if (synced !== true) return "Welcome back"
        if (d === undefined) d = new Date()
        var m = d.getMonth() + 1, day = d.getDate(), h = d.getHours(), wd = d.getDay()
        if (m === 1 && day === 1) return "Happy New Year"
        if (m === 12 && (day === 24 || day === 25)) return "Merry Christmas"
        if (m === 10 && day === 31) return "Happy Halloween"
        if (m === 7 && day === 4) return "Happy Fourth"
        if (wd === 5 && h >= 17) return "Weekend starts here"
        if ((wd === 6 || wd === 0) && h >= 5 && h <= 11) return "Weekend morning"
        var dayOfYear = Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86400000)
        var v = dayOfYear % 3
        if (h >= 5 && h <= 11) return ["Good morning", "Morning, let's roll", "Coffee and the open road"][v]
        if (h >= 12 && h <= 16) return ["Good afternoon", "Afternoon drive", "Plenty of daylight left"][v]
        if (h >= 17 && h <= 21) return ["Good evening", "Evening cruise", "Golden hour"][v]
        return ["Late night run", "Night drive", "Quiet roads tonight"][v]
    }
    // Read when the greeting fades in, not at creation, so the clock has had
    // the first second of the splash to be asked about.
    property string greetingText: ""
    function readGreeting() {
        greetingText = greeting(new Date(), typeof system !== "undefined" && system.clockSynced)
    }

    Item {
        id: stage
        width: Math.min(parent.width * 0.70, 900)
        height: width * splash.imageH / splash.imageW
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -40

        Image {
            id: truck
            anchors.fill: parent
            source: Qt.resolvedUrl("../assets/baja-boot.png")
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 900
            smooth: true
            mipmap: true
        }

        // Headlights: a warm glow on each lens, the far one smaller. The truck
        // faces the viewer, so no side beam, just light on the lenses.
        Item {
            id: glow
            anchors.fill: parent
            opacity: 0
            HeadGlow { at: splash.nearHead; size: stage.width * 0.20 }
            HeadGlow { at: splash.farHead; size: stage.width * 0.09 }
        }
    }

    // Placed in its parent (the glow layer, which fills the truck image).
    component HeadGlow: Canvas {
        property point at
        property real size
        width: size; height: size
        x: parent.width * at.x - width / 2
        y: parent.height * at.y - height / 2
        onSizeChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var r = width / 2
            var g = ctx.createRadialGradient(r, r, 0, r, r, r)
            g.addColorStop(0, "rgba(255, 250, 235, 1)")
            g.addColorStop(0.18, "rgba(255, 240, 210, 0.75)")
            g.addColorStop(0.5, "rgba(255, 228, 185, 0.18)")
            g.addColorStop(1, "rgba(255, 220, 170, 0)")
            ctx.fillStyle = g
            ctx.fillRect(0, 0, width, height)
        }
    }

    // The loading bar, carried on from the boot screen: a segment sweeping to
    // and fro in a dim track. Square, 4 px, the same place and colours as
    // deploy/plymouth/baja.script, so the hand-over doesn't jump.
    Item {
        id: bar
        width: Math.round(Math.min(splash.width * 0.22, 280))
        height: 4
        anchors.horizontalCenter: parent.horizontalCenter
        y: stage.y + stage.height + 56

        Rectangle { anchors.fill: parent; color: "#16202E" }
        Rectangle {
            id: segment
            width: Math.round(bar.width * 0.3)
            height: parent.height
            color: "#5B8FD0"
        }
        // There and back every 1.6 s, eased at each end like the boot screen's.
        SequentialAnimation {
            id: sweep
            running: true
            loops: Animation.Infinite
            NumberAnimation { target: segment; property: "x"; from: 0; to: bar.width - segment.width; duration: 800; easing.type: Easing.InOutSine }
            NumberAnimation { target: segment; property: "x"; from: bar.width - segment.width; to: 0; duration: 800; easing.type: Easing.InOutSine }
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
            color: Theme.base.text   // always the dark set: the ground is fixed near-black
            numeric: true
            font.pixelSize: 44
            font.weight: Theme.numWeight
            font.letterSpacing: 10
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 120; height: 3; radius: 1.5
            color: "#5B8FD0"     // the loading bar's Atlantic blue, whatever the style
        }
        // Caption under the name: sentence case, no tracking, dimmed.
        Label {
            id: greetingLabel
            anchors.horizontalCenter: parent.horizontalCenter
            text: splash.greetingText
            color: Theme.base.textDim
            font.pixelSize: Theme.fontBody
            opacity: 0
        }
    }

    SequentialAnimation {
        running: true
        // The dashboard is up by the time this shows: one more sweep, then
        // the bar fills (loaded) and fades as the headlights come on.
        PauseAnimation { duration: 500 }
        ScriptAction { script: sweep.stop() }
        ParallelAnimation {
            NumberAnimation { target: segment; property: "x"; to: 0; duration: 220; easing.type: Easing.OutQuad }
            NumberAnimation { target: segment; property: "width"; to: bar.width; duration: 220; easing.type: Easing.OutQuad }
        }
        NumberAnimation { target: bar; property: "opacity"; to: 0; duration: 250 }
        // Headlights flick on: a quick blip, then full.
        NumberAnimation { target: glow; property: "opacity"; to: 0.6; duration: 90 }
        NumberAnimation { target: glow; property: "opacity"; to: 0.15; duration: 110 }
        NumberAnimation { target: glow; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutQuad }
        NumberAnimation { target: title; property: "opacity"; to: 1; duration: 500 }
        ScriptAction { script: splash.readGreeting() }
        NumberAnimation { target: greetingLabel; property: "opacity"; to: 1; duration: 400 }
        // Shortened by the greeting's fade so the splash runs no longer overall.
        PauseAnimation { duration: 700 }
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

    // A MouseArea, not a TapHandler: a handler only takes a passive grab, so
    // the press would also reach the Home page and nav rail underneath. The
    // MouseArea accepts it, and keeps swallowing touches while the fade runs.
    MouseArea {
        anchors.fill: parent
        onPressed: splash.finish()
    }
}

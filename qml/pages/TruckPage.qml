import QtQuick
import QtQuick.Layouts
import QtQuick3D
import "../components"
import "../assets/truck"

// The Baja in 3D: turns slowly on its own, drag sideways to spin it (let go
// mid-swipe and it keeps turning, then slows). Opening the page whips it
// round once, at most every 30 s. Tap the name five times within 3 s for a
// showroom double spin and a one-line aside. Only
// renders while this page is on screen (PageHost hides it otherwise), so
// it costs nothing the rest of the time. The model is baja-3d.glb (~123k
// triangles) converted to Qt's own mesh files, which load at once, with
// its materials put right (tools/convert_truck.py): glossy gold paint,
// grey cladding, tinted glass, and BAJA plates. Under it, this trip so
// far (the live readouts are on Home and Gauges).
Item {
    id: page
    signal navigate(int index)
    property Trip trip: null

    property real spin: -35            // degrees, around the vertical axis
    property bool dragging: false

    // Slow idle turntable; pauses while you drag and for a moment after.
    NumberAnimation on spin {
        id: turntable
        running: page.visible && !page.dragging && !resume.running && !intro.running && !flick.running
        from: page.spin; to: page.spin + 360
        duration: 48000
        loops: Animation.Infinite
    }
    Timer { id: resume; interval: 2500 }

    // Showroom spin: one fast turn when the page opens, then the turntable.
    property real lastIntro: 0         // Date.now() of the last one
    NumberAnimation {
        id: intro
        target: page; property: "spin"
        duration: 1400
        easing.type: Easing.OutCubic
    }
    function playIntro() {
        if (dragging || Date.now() - lastIntro < 30000) return
        lastIntro = Date.now()
        flick.stop()
        intro.duration = 1400
        intro.from = spin
        intro.to = spin + 360
        intro.start()
    }

    // Easter egg: five quick taps on the name give a double spin and a
    // one-line aside for 4 s. Only one-shot animations; no timer runs idle.
    property int eggTaps: 0
    property real eggFirstTap: 0       // Date.now() of the first tap in the run
    property string eggLine: ""        // shown in place of "Drag to spin"
    property int eggIndex: 0           // next aside, in order
    readonly property var eggLines: [
        "Half car. Half truck. All Baja.",
        "Built in Lafayette, Indiana",
        "210 hp of turbo flat-four",
        "The bed is just a very open trunk",
        "Sport Utility Truck, est. 2003"
    ]
    function eggTap() {
        if (dragging) return
        if (Date.now() - eggFirstTap > 3000) {
            eggTaps = 0
            eggFirstTap = Date.now()
        }
        eggTaps++
        if (eggTaps < 5) return
        eggTaps = 0
        eggLine = eggLines[eggIndex]
        eggIndex = (eggIndex + 1) % eggLines.length
        flick.stop()
        intro.duration = 2000
        intro.from = spin
        intro.to = spin + 720
        intro.start()
        eggHold.restart()
    }
    SequentialAnimation {
        id: eggHold
        PauseAnimation { duration: 4000 }
        ScriptAction { script: page.eggLine = "" }
    }
    onVisibleChanged: if (visible) playIntro()
    Component.onCompleted: if (visible) playIntro()

    // Flick: a swipe released at speed keeps turning and slows to a stop.
    NumberAnimation {
        id: flick
        target: page; property: "spin"
        duration: 900
        easing.type: Easing.OutQuad
        onRunningChanged: if (!running && !page.dragging) resume.restart()
    }

    // A soft pool of light on the floor under the truck, so it stands on
    // something (flat and fixed, like the camera: costs nothing to draw).
    Image {
        anchors { horizontalCenter: view.horizontalCenter; top: view.top; topMargin: view.height * 0.6 }
        width: Math.min(view.width * 0.85, 940)
        height: width * 0.25
        // Light on a dark page, shade on a light one.
        source: Qt.resolvedUrl(Theme.dark ? "../assets/truck/floor.png" : "../assets/truck/floor-shade.png")
        opacity: Theme.dark ? 0.12 : 0.14
    }

    View3D {
        id: view
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: readouts.top }

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            specularAAEnabled: true          // no sparkle along glossy edges
            tonemapMode: SceneEnvironment.TonemapModeFilmic
            // A generated photo-studio environment (dark room, big soft
            // panels). Metallic car paint gets its colour from reflecting
            // surroundings; with lights alone it renders nearly black.
            // Pre-filtered once with Qt's balsam (tools/make_studio_hdr.py):
            // filtering the .hdr at runtime froze the Pi for 7 s.
            lightProbe: Texture { source: Qt.resolvedUrl("../assets/studio.ktx") }
            probeExposure: 1.25
            probeOrientation: Qt.vector3d(0, -page.spin, 0)   // reflections stay put as it turns
        }

        // Model units are metres; scale to centimetres, Quick 3D's defaults.
        PerspectiveCamera {
            position: Qt.vector3d(0, 140, 490)
            eulerRotation.x: -9
            fieldOfView: 38
        }

        // The studio environment does most of the lighting; one key light
        // adds definition and a warm rim separates the truck from the page.
        DirectionalLight { eulerRotation: Qt.vector3d(-55, -25, 0); brightness: 1.1 }
        DirectionalLight { eulerRotation: Qt.vector3d(-25, 170, 0); brightness: 0.5; color: "#ffe2c4" }

        Node {
            eulerRotation.y: page.spin

            Node {
                scale: Qt.vector3d(100, 100, 100)          // metres to centimetres
                BajaModel {}
                // Its plates: the model's size and place, with BAJA on.
                Model {
                    source: "#Rectangle"
                    position: Qt.vector3d(0.0035, 0.5108, 2.4245)
                    scale: Qt.vector3d(0.0052, 0.0011, 1)
                    materials: plate
                }
                Model {
                    source: "#Rectangle"
                    position: Qt.vector3d(-0.0035, 0.7608, -2.3365)
                    eulerRotation.y: 180
                    scale: Qt.vector3d(0.0052, 0.0011, 1)
                    materials: plate
                }
                PrincipledMaterial {
                    id: plate
                    baseColorMap: Texture { source: Qt.resolvedUrl("../assets/truck/plate.png"); generateMipmaps: true; mipFilter: Texture.Linear }
                    roughness: 0.45
                }
            }

            // Soft pre-drawn contact shadow that turns with the truck: looks
            // better on the dark page than a real-time shadow and costs
            // almost nothing (no shadow map pass).
            Model {
                source: "#Rectangle"
                y: 1
                eulerRotation.x: -90
                scale: Qt.vector3d(2.9, 6.0, 1)    // ~ the truck's footprint (cm)
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColorMap: Texture { source: Qt.resolvedUrl("../assets/truck-shadow.png") }
                    alphaMode: PrincipledMaterial.Blend
                }
            }
        }
    }

    // Drag sideways anywhere to spin the truck.
    DragHandler {
        target: null
        property real startSpin: 0
        property real lastVx: 0        // px/s, in case it reads 0 at release
        property real lastVxAt: 0      // when lastVx was recorded (ms)
        onActiveChanged: {
            page.dragging = active
            if (active) {
                intro.stop()
                flick.stop()
                startSpin = page.spin
                lastVx = 0
                lastVxAt = 0
            } else {
                var v = centroid.velocity.x
                if (v === 0 && Date.now() - lastVxAt < 100) v = lastVx
                var dps = v * 0.35     // degrees/s, same factor as the drag
                if (Math.abs(dps) > 40) {
                    flick.from = page.spin
                    flick.to = page.spin + Math.max(-540, Math.min(540, dps * 0.6))
                    flick.start()      // resume starts when it finishes
                } else {
                    resume.restart()
                }
            }
        }
        onCentroidChanged: if (active) { lastVx = centroid.velocity.x; lastVxAt = Date.now() }
        onTranslationChanged: if (active) page.spin = startSpin + translation.x * 0.35
    }

    // The truck's name, plus this trip in the same strip as Home's readouts.
    Column {
        anchors { left: parent.left; top: parent.top; leftMargin: 8; topMargin: 4 }
        spacing: 2
        // Tap handler only: a drag on the name still reaches the page's DragHandler.
        TapHandler { onTapped: page.eggTap() }
        Label {
            text: "2005 Subaru Baja Turbo"
            font.pixelSize: Theme.fontTitle
            font.weight: Font.DemiBold
        }
        Row {
            spacing: 8
            Icon {
                name: "rotate"; size: 18; color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
                visible: page.eggLine === ""
            }
            Label {
                text: page.eggLine !== "" ? page.eggLine : "Drag to spin"
                color: Theme.textDim; font.pixelSize: Theme.fontSmall
            }
        }
    }

    Card {
        id: readouts
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 128

        readonly property real minutes: page.trip ? Math.floor(page.trip.movingSeconds / 60) : 0

        RowLayout {
            anchors { fill: parent; margins: 20 }
            Readout {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                label: page.trip ? "Trip since " + Units.timeText(page.trip.started) : "Trip"
                value: page.trip ? (page.trip.metres / (Units.metric ? 1000 : 1609.34)).toFixed(1) : "—"
                unit: Units.metric ? "km" : "mi"
            }
            Readout {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                label: "Driving"
                value: readouts.minutes < 60 ? readouts.minutes
                       : Math.floor(readouts.minutes / 60) + ":" + (readouts.minutes % 60 < 10 ? "0" : "") + readouts.minutes % 60
                unit: readouts.minutes < 60 ? "min" : "h"
            }
            Readout {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                label: "Average"
                value: page.trip && page.trip.movingSeconds > 0 ? Math.round(Units.speed(page.trip.averageMph)) : "—"
                unit: Units.speedUnit
            }
            Readout {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                label: "Peak boost"
                value: page.trip && page.trip.boostKnown ? Units.boost(page.trip.peakBoost).toFixed(Units.boostDecimals) : "—"
                unit: Units.boostUnit
            }
        }
    }
}

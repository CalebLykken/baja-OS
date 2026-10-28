import QtQuick
import QtQuick.Layouts
import QtQuick3D
import "../components"
import "../assets/truck"

// The Baja in 3D: turns slowly on its own, drag sideways to spin it. Only
// renders while this page is on screen (PageHost hides it otherwise), so
// it costs nothing the rest of the time. The model is baja-3d.glb (~123k
// triangles) converted to Qt's own mesh files, which load at once, with
// its materials put right (tools/convert_truck.py): glossy gold paint,
// grey cladding, tinted glass, and BAJA plates.
Item {
    id: page
    signal navigate(int index)

    property real spin: -35            // degrees, around the vertical axis
    property bool dragging: false

    // Slow idle turntable; pauses while you drag and for a moment after.
    NumberAnimation on spin {
        id: turntable
        running: page.visible && !page.dragging && !resume.running
        from: page.spin; to: page.spin + 360
        duration: 48000
        loops: Animation.Infinite
    }
    Timer { id: resume; interval: 2500 }

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
        onActiveChanged: {
            page.dragging = active
            if (active) startSpin = page.spin
            else resume.restart()
        }
        onTranslationChanged: if (active) page.spin = startSpin + translation.x * 0.35
    }

    // The truck's name, plus a few live readouts in the same strip as Home.
    Column {
        anchors { left: parent.left; top: parent.top; leftMargin: 8; topMargin: 4 }
        spacing: 2
        Label {
            text: "2005 Subaru Baja Turbo"
            font.pixelSize: Theme.fontTitle
            font.weight: Font.DemiBold
        }
        Row {
            spacing: 8
            Icon { name: "rotate"; size: 18; color: Theme.textDim; anchors.verticalCenter: parent.verticalCenter }
            Label { text: "Drag to spin"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
        }
    }

    Card {
        id: readouts
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 128

        RowLayout {
            anchors { fill: parent; margins: 20 }
            Readout { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Speed"; value: vehicle.engineKnown ? Math.round(Units.speed(vehicle.speed)) : "—"; unit: Units.speedUnit }
            Readout { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Gear"; value: vehicle.engineKnown ? vehicle.gear || "N" : "—"; unit: "" }
            Readout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: "Boost"; value: vehicle.engineKnown ? Units.boost(vehicle.boost).toFixed(Units.boostDecimals) : "—"; unit: Units.boostUnit
                warning: vehicle.warnings.indexOf("boost") >= 0
            }
            Readout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: "Coolant"; value: vehicle.engineKnown ? Math.round(Units.temp(vehicle.coolant)) : "—"; unit: Units.tempUnit
                warning: vehicle.warnings.indexOf("coolant") >= 0
            }
        }
    }
}

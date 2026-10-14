import QtQuick
import QtQuick.Layouts
import QtQuick3D
import QtQuick3D.AssetUtils
import "../components"

// The Baja in 3D: turns slowly on its own, drag sideways to spin it. Only
// renders while this page is on screen (PageHost hides it otherwise), so
// it costs nothing the rest of the time. The model is the portfolio's
// baja.glb with trim, interior and tyres simplified (~123k triangles).
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

    View3D {
        id: view
        anchors.fill: parent

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            tonemapMode: SceneEnvironment.TonemapModeFilmic
            // A generated photo-studio environment (dark room, big soft
            // panels). Metallic car paint gets its colour from reflecting
            // surroundings; with lights alone it renders nearly black.
            lightProbe: Texture { source: Qt.resolvedUrl("../assets/studio.hdr") }
            probeExposure: 1.1
            probeOrientation: Qt.vector3d(0, -page.spin, 0)   // reflections stay put as it turns
        }

        // Model units are metres; scale to centimetres, Quick 3D's defaults.
        PerspectiveCamera {
            position: Qt.vector3d(0, 175, 640)
            eulerRotation.x: -10
            fieldOfView: 38
        }

        // The studio environment does most of the lighting; one key light
        // adds definition and a warm rim separates the truck from the page.
        DirectionalLight { eulerRotation: Qt.vector3d(-55, -25, 0); brightness: 0.8 }
        DirectionalLight { eulerRotation: Qt.vector3d(-25, 170, 0); brightness: 0.5; color: "#ffe2c4" }

        Node {
            eulerRotation.y: page.spin

            RuntimeLoader {
                id: truck
                source: Qt.resolvedUrl("../assets/baja-3d.glb")
                scale: Qt.vector3d(100, 100, 100)
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

    Label {
        visible: truck.status === RuntimeLoader.Error
        anchors.centerIn: parent
        text: "Couldn't load the 3D model"
        color: Theme.textDim
        font.pixelSize: Theme.fontBody
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

    // Title, plus a few live readouts along the bottom.
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

    RowLayout {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 8; rightMargin: 8 }
        Readout { Layout.fillWidth: true; label: "Speed"; value: Math.round(vehicle.speed); unit: "mph" }
        Readout { Layout.fillWidth: true; label: "Gear"; value: vehicle.gear; unit: "" }
        Readout {
            Layout.fillWidth: true
            label: "Boost"; value: vehicle.boost.toFixed(1); unit: "psi"
            warning: vehicle.boost > 15
        }
        Readout {
            Layout.fillWidth: true
            label: "Coolant"; value: Math.round(vehicle.coolant); unit: "°F"
            warning: vehicle.coolant > 230
        }
    }
}

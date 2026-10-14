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
        }

        // Model units are metres; scale to centimetres, Quick 3D's defaults.
        PerspectiveCamera {
            position: Qt.vector3d(0, 190, 820)
            eulerRotation.x: -9
            fieldOfView: 38
        }

        // Key light from above-front, casting the ground shadow.
        DirectionalLight {
            eulerRotation: Qt.vector3d(-55, -25, 0)
            brightness: 1.6
            castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityHigh
            shadowFactor: 55
            shadowBias: 8
        }
        // Soft fill from the camera side and a warm rim from behind.
        DirectionalLight { eulerRotation: Qt.vector3d(-10, 20, 0); brightness: 0.55 }
        DirectionalLight { eulerRotation: Qt.vector3d(-25, 170, 0); brightness: 0.7; color: "#ffe2c4" }
        DirectionalLight { eulerRotation: Qt.vector3d(70, 0, 0); brightness: 0.25 }   // lifts the underside

        Node {
            eulerRotation.y: page.spin

            RuntimeLoader {
                id: truck
                source: Qt.resolvedUrl("../assets/baja-3d.glb")
                scale: Qt.vector3d(100, 100, 100)
            }
        }

        // Shadow catcher: the same colour as the page, so only the shadow shows.
        Model {
            source: "#Rectangle"
            eulerRotation.x: -90
            scale: Qt.vector3d(14, 14, 1)
            receivesShadows: true
            materials: PrincipledMaterial {
                baseColor: Theme.bg
                roughness: 1
                lighting: PrincipledMaterial.FragmentLighting
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

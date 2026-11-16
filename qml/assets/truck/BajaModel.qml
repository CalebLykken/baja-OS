// The Baja, converted from baja-3d.glb by Qt's balsam and fixed up by
// tools/convert_truck.py (colours, materials, plates). Generated: edit
// that script rather than this file.
import QtQuick
import QtQuick3D

Node {
    id: node

    // Resources
    PrincipledMaterial {
        id: licPlate_yellow_064_material
        objectName: "LicPlate_yellow.064"
        baseColor: "#ffddbc1c"
        roughness: 0.3400000035762787
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: chrome_173_material
        objectName: "chrome.173"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: blue_027_material
        objectName: "blue.027"
        baseColor: "#ff353b81"
        metalness: 0.8199999928474426
        roughness: 0.2800000011920929
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: carpaint_second_011_material
        objectName: "carpaint_second.011"
        baseColor: "#1d3557"
        roughness: 0.75
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        metalness: 0
    }
    PrincipledMaterial {
        id: black_173_material
        objectName: "black.173"
        baseColor: "#ff2e2e2e"
        roughness: 1
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: clearglass_173_material
        objectName: "clearglass.173"
        baseColor: "#0d1013"
        roughness: 0.45
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        metalness: 0
        specularAmount: 0.2
    }
    PrincipledMaterial {
        id: carpaint_173_material
        objectName: "carpaint.173"
        baseColor: "#1d3557"
        metalness: 0
        roughness: 0.24
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: mirror_163_material
        objectName: "mirror.163"
        baseColor: "#fff6f8f9"
        metalness: 1
        roughness: 0.012000000104308128
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: windowglass_162_material
        objectName: "windowglass.162"
        baseColor: "#0d1013"
        roughness: 0.45
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        metalness: 0
        specularAmount: 0.2
    }
    PrincipledMaterial {
        id: darkglass_022_material
        objectName: "darkglass.022"
        baseColor: "#0a0b0d"
        roughness: 0.45
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
        metalness: 0
        specularAmount: 0.2
    }
    PrincipledMaterial {
        id: interior_160_material
        objectName: "interior.160"
        baseColor: "#ff535151"
        roughness: 1
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: licPlate_black_064_material
        objectName: "LicPlate_black.064"
        baseColor: "#ff262626"
        roughness: 0.3400000035762787
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: licPlate_white_064_material
        objectName: "LicPlate_white.064"
        baseColor: "#ffeeeeec"
        roughness: 0.3400000035762787
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: licPlate_blue_064_material
        objectName: "LicPlate_blue.064"
        baseColor: "#ff263295"
        roughness: 0.3400000035762787
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: lens_amberL_material
        objectName: "lens_amberL"
        baseColor: "#ffe09a32"
        roughness: 0.05000000074505806
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: lens_amberR_material
        objectName: "lens_amberR"
        baseColor: "#ffe09a32"
        roughness: 0.05000000074505806
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: lens_brake_material
        objectName: "lens_brake"
        baseColor: "#ffb32626"
        roughness: 0.05000000074505806
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: lens_clear_material
        objectName: "lens_clear"
        baseColor: "#ffffff"
        roughness: 0.03
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Blend
        opacity: 0.22
    }
    PrincipledMaterial {
        id: lens_redL_material
        objectName: "lens_redL"
        baseColor: "#ffb32626"
        roughness: 0.05000000074505806
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: lens_redR_material
        objectName: "lens_redR"
        baseColor: "#ffb32626"
        roughness: 0.05000000074505806
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_brake_material
        objectName: "refl_brake"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_fog_material
        objectName: "refl_fog"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_head_material
        objectName: "refl_head"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_roof_material
        objectName: "refl_roof"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_tailL_material
        objectName: "refl_tailL"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_tailR_material
        objectName: "refl_tailR"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_turnL_material
        objectName: "refl_turnL"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: refl_turnR_material
        objectName: "refl_turnR"
        baseColor: "#fff1f2f6"
        metalness: 1
        roughness: 0.04500000178813934
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: scoop_duct_material
        objectName: "scoop_duct"
        baseColor: "#ff1c1c1c"
        roughness: 0.6600000262260437
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: rim_156_material
        objectName: "rim.156"
        baseColor: "#ffceced0"
        metalness: 1
        roughness: 0.35
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: brakedisk_129_material
        objectName: "brakedisk.129"
        baseColor: "#ff908e8b"
        metalness: 1
        roughness: 0.5
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }
    PrincipledMaterial {
        id: tire_173_material
        objectName: "tire.173"
        baseColor: "#ff222222"
        roughness: 0.9
        cullMode: PrincipledMaterial.NoCulling
        alphaMode: PrincipledMaterial.Opaque
    }

    // Nodes:
    Node {
        id: root
        objectName: "ROOT"
        Model {
            id: body
            visible: false
            objectName: "Body"
            source: "meshes/body_mesh.mesh"
            materials: [
                licPlate_yellow_064_material
            ]
        }
        Model {
            id: body_001
            objectName: "Body.001"
            source: "meshes/body_001_mesh.mesh"
            materials: [
                chrome_173_material
            ]
        }
        Model {
            id: body_002
            objectName: "Body.002"
            source: "meshes/body_002_mesh.mesh"
            materials: [
                blue_027_material
            ]
        }
        Model {
            id: body_003
            objectName: "Body.003"
            source: "meshes/body_003_mesh.mesh"
            materials: [
                carpaint_second_011_material
            ]
        }
        Model {
            id: body_004
            objectName: "Body.004"
            source: "meshes/body_004_mesh.mesh"
            materials: [
                black_173_material
            ]
        }
        Model {
            id: body_005
            objectName: "Body.005"
            source: "meshes/body_005_mesh.mesh"
            materials: [
                clearglass_173_material
            ]
        }
        Model {
            id: body_006
            objectName: "Body.006"
            source: "meshes/body_006_mesh.mesh"
            materials: [
                carpaint_173_material
            ]
        }
        Model {
            id: body_007
            objectName: "Body.007"
            source: "meshes/body_007_mesh.mesh"
            materials: [
                mirror_163_material
            ]
        }
        Model {
            id: body_008
            objectName: "Body.008"
            source: "meshes/body_008_mesh.mesh"
            materials: [
                windowglass_162_material
            ]
        }
        Model {
            id: body_009
            objectName: "Body.009"
            source: "meshes/body_009_mesh.mesh"
            materials: [
                darkglass_022_material
            ]
        }
        Model {
            id: body_010
            visible: false
            objectName: "Body.010"
            source: "meshes/body_010_mesh.mesh"
            materials: [
                interior_160_material
            ]
        }
        Model {
            id: body_011
            visible: false
            objectName: "Body.011"
            source: "meshes/body_011_mesh.mesh"
            materials: [
                licPlate_black_064_material
            ]
        }
        Model {
            id: body_012
            visible: false
            objectName: "Body.012"
            source: "meshes/body_012_mesh.mesh"
            materials: [
                licPlate_white_064_material
            ]
        }
        Model {
            id: body_013
            visible: false
            objectName: "Body.013"
            source: "meshes/body_013_mesh.mesh"
            materials: [
                licPlate_blue_064_material
            ]
        }
        Model {
            id: lens_amberL
            objectName: "Lens_amberL"
            source: "meshes/lens_amberL_mesh.mesh"
            materials: [
                lens_amberL_material
            ]
        }
        Model {
            id: lens_amberR
            objectName: "Lens_amberR"
            source: "meshes/lens_amberR_mesh.mesh"
            materials: [
                lens_amberR_material
            ]
        }
        Model {
            id: lens_brake
            objectName: "Lens_brake"
            source: "meshes/lens_brake_mesh.mesh"
            materials: [
                lens_brake_material
            ]
        }
        Model {
            id: lens_clear
            objectName: "Lens_clear"
            source: "meshes/lens_clear_mesh.mesh"
            materials: [
                lens_clear_material
            ]
        }
        Model {
            id: lens_redL
            objectName: "Lens_redL"
            source: "meshes/lens_redL_mesh.mesh"
            materials: [
                lens_redL_material
            ]
        }
        Model {
            id: lens_redR
            objectName: "Lens_redR"
            source: "meshes/lens_redR_mesh.mesh"
            materials: [
                lens_redR_material
            ]
        }
        Model {
            id: refl_brake
            objectName: "Refl_brake"
            source: "meshes/refl_brake_mesh.mesh"
            materials: [
                refl_brake_material
            ]
        }
        Model {
            id: refl_fog
            objectName: "Refl_fog"
            source: "meshes/refl_fog_mesh.mesh"
            materials: [
                refl_fog_material
            ]
        }
        Model {
            id: refl_head
            objectName: "Refl_head"
            source: "meshes/refl_head_mesh.mesh"
            materials: [
                refl_head_material
            ]
        }
        Model {
            id: refl_roof
            objectName: "Refl_roof"
            source: "meshes/refl_roof_mesh.mesh"
            materials: [
                refl_roof_material
            ]
        }
        Model {
            id: refl_tailL
            objectName: "Refl_tailL"
            source: "meshes/refl_tailL_mesh.mesh"
            materials: [
                refl_tailL_material
            ]
        }
        Model {
            id: refl_tailR
            objectName: "Refl_tailR"
            source: "meshes/refl_tailR_mesh.mesh"
            materials: [
                refl_tailR_material
            ]
        }
        Model {
            id: refl_turnL
            objectName: "Refl_turnL"
            source: "meshes/refl_turnL_mesh.mesh"
            materials: [
                refl_turnL_material
            ]
        }
        Model {
            id: refl_turnR
            objectName: "Refl_turnR"
            source: "meshes/refl_turnR_mesh.mesh"
            materials: [
                refl_turnR_material
            ]
        }
        Model {
            id: scoop
            objectName: "Scoop"
            source: "meshes/scoop_mesh.mesh"
            materials: [
                carpaint_173_material,
                scoop_duct_material
            ]
        }
        Model {
            id: wheel_FL
            objectName: "Wheel_FL"
            position: Qt.vector3d(0.716517, 0.346185, 1.46317)
            source: "meshes/wheel_FL_mesh.mesh"
            materials: [
                rim_156_material
            ]
        }
        Model {
            id: wheel_FL_001
            objectName: "Wheel_FL.001"
            position: Qt.vector3d(0.716517, 0.346185, 1.46317)
            source: "meshes/wheel_FL_001_mesh.mesh"
            materials: [
                brakedisk_129_material
            ]
        }
        Model {
            id: wheel_FL_002
            objectName: "Wheel_FL.002"
            position: Qt.vector3d(0.716517, 0.346185, 1.46317)
            source: "meshes/wheel_FL_002_mesh.mesh"
            materials: [
                tire_173_material
            ]
        }
        Model {
            id: wheel_FR
            objectName: "Wheel_FR"
            position: Qt.vector3d(-0.709659, 0.346127, 1.46291)
            source: "meshes/wheel_FR_mesh.mesh"
            materials: [
                rim_156_material
            ]
        }
        Model {
            id: wheel_FR_001
            objectName: "Wheel_FR.001"
            position: Qt.vector3d(-0.709659, 0.346127, 1.46291)
            source: "meshes/wheel_FR_001_mesh.mesh"
            materials: [
                brakedisk_129_material
            ]
        }
        Model {
            id: wheel_FR_002
            objectName: "Wheel_FR.002"
            position: Qt.vector3d(-0.709659, 0.346127, 1.46291)
            source: "meshes/wheel_FR_002_mesh.mesh"
            materials: [
                tire_173_material
            ]
        }
        Model {
            id: wheel_RL
            objectName: "Wheel_RL"
            position: Qt.vector3d(0.716556, 0.346112, -1.19359)
            source: "meshes/wheel_RL_mesh.mesh"
            materials: [
                rim_156_material
            ]
        }
        Model {
            id: wheel_RL_001
            objectName: "Wheel_RL.001"
            position: Qt.vector3d(0.716556, 0.346112, -1.19359)
            source: "meshes/wheel_RL_001_mesh.mesh"
            materials: [
                brakedisk_129_material
            ]
        }
        Model {
            id: wheel_RL_002
            objectName: "Wheel_RL.002"
            position: Qt.vector3d(0.716556, 0.346112, -1.19359)
            source: "meshes/wheel_RL_002_mesh.mesh"
            materials: [
                tire_173_material
            ]
        }
        Model {
            id: wheel_RR
            objectName: "Wheel_RR"
            position: Qt.vector3d(-0.70975, 0.345985, -1.19355)
            source: "meshes/wheel_RR_mesh.mesh"
            materials: [
                rim_156_material
            ]
        }
        Model {
            id: wheel_RR_001
            objectName: "Wheel_RR.001"
            position: Qt.vector3d(-0.70975, 0.345985, -1.19355)
            source: "meshes/wheel_RR_001_mesh.mesh"
            materials: [
                brakedisk_129_material
            ]
        }
        Model {
            id: wheel_RR_002
            objectName: "Wheel_RR.002"
            position: Qt.vector3d(-0.70975, 0.345985, -1.19355)
            source: "meshes/wheel_RR_002_mesh.mesh"
            materials: [
                tire_173_material
            ]
        }
    }

    // Animations:
}

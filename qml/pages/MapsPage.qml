import QtQuick
import "../components"

// The offline map in a framed card, with zoom and recentre keys on the right
// and the OpenStreetMap credit in the corner. The map (a web engine) starts
// the first time this page is opened and then stays loaded. Until it's
// drawn, or if it can't be, the card says why in plain words.
Item {
    id: page
    objectName: "mapsPage"
    signal navigate(int index)

    property bool opened: false
    property bool mapReady: false
    property string problem: ""
    onVisibleChanged: if (visible) { opened = true; if (hasMaps) maps.refresh() }
    // Start the map in the background a little after start-up, so it's
    // ready (and following the truck) the first time the page opens.
    Timer { interval: 6000; running: true; onTriggered: page.opened = true }

    readonly property bool hasMaps: typeof maps !== "undefined"
    readonly property bool hasFix: typeof gps !== "undefined" && gps.hasFix
    readonly property var map: mapLoader.item

    Card {
        id: frame
        anchors.fill: parent

        Loader {
            id: mapLoader
            anchors { fill: parent; margins: Theme.border }
            active: page.opened && page.hasMaps && maps.webEngine && maps.ready
            source: "MapView.qml"
            onStatusChanged: if (status === Loader.Error) page.problem = "The map engine didn't start"
        }
        Connections {
            target: page.map
            ignoreUnknownSignals: true
            function onReady(ms) { page.mapReady = true; console.log("Map: drawn in " + ms + " ms") }
            function onFailed(message) { page.problem = message }
            function onBenchDone(result) { console.log("Map bench: " + JSON.stringify(result)) }
        }

        // Fill the four corners outside the frame's curve, which the square
        // map would otherwise poke through.
        Repeater {
            model: 4
            Canvas {
                readonly property bool atRight: index === 1 || index === 2
                readonly property bool atBottom: index >= 2
                width: Theme.radius; height: Theme.radius
                x: atRight ? frame.width - width : 0
                y: atBottom ? frame.height - height : 0
                rotation: [0, 90, 180, 270][index]
                onPaint: {
                    var ctx = getContext("2d"), r = width
                    ctx.reset()
                    ctx.fillStyle = Theme.bg
                    ctx.beginPath()
                    ctx.moveTo(0, 0); ctx.lineTo(r, 0)
                    ctx.arc(r, r, r, -Math.PI / 2, Math.PI, true)
                    ctx.closePath()
                    ctx.fill()
                }
                Connections { target: Theme; function onStyleChanged() { requestPaint() } }
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: Theme.radius
            color: "transparent"
            border.width: Theme.border
            border.color: Theme.line
        }

        // Until the map is drawn: what's happening, or what's missing.
        Column {
            visible: !page.mapReady
            anchors.centerIn: parent
            width: parent.width - 80
            spacing: 14
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "map"
                color: Theme.textDim
                size: 96
            }
            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                text: !page.hasMaps || !maps.webEngine ? "The map needs Qt WebEngine"
                      : !maps.ready ? "No map installed yet"
                      : page.problem !== "" ? "The map didn't load"
                      : "Loading the map"
            }
            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: Theme.textDim
                font.pixelSize: Theme.fontBody
                text: !page.hasMaps || !maps.webEngine ? "Run deploy/setup-pi.sh on the Pi to install it"
                      : !maps.ready ? "Run deploy/maps/install-map.sh on the Pi to download the Seattle area"
                      : page.problem !== "" ? page.problem
                      : maps.region
            }
        }

        // Keys down the right edge.
        Column {
            visible: page.mapReady
            anchors { right: parent.right; top: parent.top; margins: 16 }
            spacing: 12
            IconButton { icon: "add"; onClicked: page.map.call("zoomIn()") }
            IconButton { icon: "remove"; onClicked: page.map.call("zoomOut()") }
        }
        Column {
            visible: page.mapReady
            anchors { right: parent.right; bottom: parent.bottom; margins: 16 }
            spacing: 12
            // North: only while the map is turned by hand; the needle points north.
            IconButton {
                visible: page.map && !page.map.following && Math.abs(page.map.bearing) > 1
                icon: "navigation"
                iconRotation: page.map ? -page.map.bearing : 0
                onClicked: page.map.call("northUp()")
            }
            // Follow the truck (lit while following), or back to Seattle
            // when there's no position yet.
            IconButton {
                icon: page.hasFix ? "navigation" : "home"
                active: page.map && page.map.following
                onClicked: page.map.call("recenter()")
            }
        }

        // Speed, top left, whenever there's a position.
        Rectangle {
            visible: page.mapReady && page.hasFix
            anchors { left: parent.left; top: parent.top; margins: 16 }
            width: speedRow.implicitWidth + 32
            height: 76
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.line
            Row {
                id: speedRow
                anchors.centerIn: parent
                spacing: 8
                Label {
                    id: speedNum
                    numeric: true
                    text: Math.round(Units.speed(gps.speed / 0.44704))
                    font.pixelSize: Theme.fontReadout
                }
                Label {
                    anchors.baseline: speedNum.baseline
                    text: Units.speedUnit
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        // OpenStreetMap's licence asks for this to be visible on the map.
        Rectangle {
            visible: page.mapReady
            anchors { left: parent.left; bottom: parent.bottom; margins: 16 }
            width: credit.implicitWidth + 24
            height: 34
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.line
            Label {
                id: credit
                anchors.centerIn: parent
                text: "© OpenStreetMap contributors"
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall - 2
            }
        }
    }
}

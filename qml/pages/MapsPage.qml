import QtQuick
import QtQuick.Layouts
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

    // Search: the sheet with the keyboard, and the place picked from it.
    property bool searching: false
    property string query: ""
    property var destination: null          // {name, label, lon, lat}
    onQueryChanged: searchDelay.restart()
    Timer {
        id: searchDelay
        interval: 180
        onTriggered: maps.search(page.query, page.hasFix ? gps.lon : 0, page.hasFix ? gps.lat : 0)
    }

    // Home and the last few places picked, saved between runs, listed when
    // the search box is empty.
    function loadJson(key, fallback) {
        if (typeof settings === "undefined") return fallback
        try { return JSON.parse(String(settings.get(key, JSON.stringify(fallback)))) } catch (e) { return fallback }
    }
    property var home: loadJson("homePlace", null)
    property var recents: loadJson("recentPlaces", [])
    readonly property var saved: (home ? [Object.assign({}, home, { label: "Home", isHome: true })] : [])
                                 .concat(recents.filter(p => !home || p.name !== home.name || p.lon !== home.lon))
    function samePlace(a, b) { return a && b && a.name === b.name && Math.abs(a.lon - b.lon) < 1e-5 && Math.abs(a.lat - b.lat) < 1e-5 }
    function remember(place) {
        var keep = { name: place.name, label: place.label, lon: place.lon, lat: place.lat }
        recents = [keep].concat(recents.filter(p => !samePlace(p, keep))).slice(0, 6)
        settings.set("recentPlaces", JSON.stringify(recents))
    }
    function toggleHome(place) {
        home = samePlace(home, place) ? null : { name: place.name, label: place.label, lon: place.lon, lat: place.lat }
        settings.set("homePlace", JSON.stringify(home))
    }

    function openSearch() { query = ""; searching = true }
    function choose(place) {
        destination = place
        searching = false
        if (!place.isHome) remember(place)
        map.call("showPlace(" + place.lon + "," + place.lat + ")")
    }
    function clearDestination() { destination = null; map.call("clearPlace()") }

    readonly property bool hasRouting: typeof routing !== "undefined"
    readonly property bool navigating: hasRouting && routing.active
    function endRoute() { routing.stop(); clearDestination() }
    function durationText(s) { return Units.durationText(s) }
    function arrivalText(s) { return Units.arrivalText(s) }

    // Straight-line distance from the truck, in metres (-1 without a position).
    function distanceTo(place) {
        if (!place || !hasFix) return -1
        var rad = Math.PI / 180
        var dx = (place.lon - gps.lon) * rad * Math.cos(gps.lat * rad) * 6371000
        var dy = (place.lat - gps.lat) * rad * 6371000
        return Math.sqrt(dx * dx + dy * dy)
    }
    function distanceText(m) { return Units.distanceText(m) }
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
            visible: page.mapReady && !page.searching
            anchors { right: parent.right; top: parent.top; margins: 16 }
            spacing: 12
            IconButton {
                visible: maps.canSearch
                icon: "search"
                onClicked: page.openSearch()
            }
            IconButton { icon: "add"; onClicked: page.map.call("zoomIn()") }
            IconButton { icon: "remove"; onClicked: page.map.call("zoomOut()") }
        }
        Column {
            visible: page.mapReady && !page.searching
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

        // The road you're on, bottom centre, while following.
        Rectangle {
            visible: page.mapReady && page.map && page.map.following && page.map.road !== "" && !page.navigating
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 16 }
            width: Math.min(roadName.implicitWidth + 40, parent.width - 420)
            height: 56
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.line
            Label {
                id: roadName
                anchors.centerIn: parent
                width: Math.min(implicitWidth, parent.width - 40)
                elide: Text.ElideRight
                text: page.map ? page.map.road : ""
                font.pixelSize: Theme.fontBody + 2
                font.weight: Font.DemiBold
            }
        }

        // The place picked from search: name, what it is, how far.
        Rectangle {
            visible: page.mapReady && page.destination !== null && !page.searching && !page.navigating
            anchors { top: parent.top; topMargin: 16; horizontalCenter: parent.horizontalCenter }
            width: Math.min(destRow.implicitWidth + 36, parent.width - 400)
            height: 80
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.line
            RowLayout {
                id: destRow
                anchors { fill: parent; leftMargin: 18; rightMargin: 12 }
                spacing: 14
                Icon { name: "place"; size: 32; color: Theme.accent }
                Column {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 380
                    Label {
                        width: parent.width
                        elide: Text.ElideRight
                        text: page.destination ? page.destination.name : ""
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    Label {
                        width: parent.width
                        elide: Text.ElideRight
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                        text: {
                            if (!page.destination) return ""
                            if (page.hasRouting && routing.error !== "") return routing.error
                            var d = page.distanceText(page.distanceTo(page.destination))
                            return d ? d + " away, " + page.destination.label.charAt(0).toLowerCase() + page.destination.label.slice(1)
                                     : page.destination.label
                        }
                    }
                }
                // Save this place as Home (lit when it is), or forget it.
                IconButton {
                    icon: "home"
                    size: 52
                    active: page.samePlace(page.home, page.destination)
                    onClicked: page.toggleHome(page.destination)
                }
                TextButton {
                    visible: page.hasRouting && routing.available
                    primary: true
                    implicitHeight: 52
                    text: routing.computing ? "Finding route" : "Go"
                    enabled: !routing.computing && page.hasFix
                    onClicked: routing.routeTo(page.destination.name, page.destination.lon, page.destination.lat)
                }
                IconButton { icon: "close"; size: 52; onClicked: page.clearDestination() }
            }
        }

        // ---- navigating: the next turn on top, the trip along the bottom ------
        Rectangle {
            visible: page.mapReady && page.navigating && !page.searching
            anchors { left: parent.left; leftMargin: 172; right: parent.right; rightMargin: 108; top: parent.top; topMargin: 16 }
            height: 112
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.accent
            RowLayout {
                anchors { fill: parent; leftMargin: 18; rightMargin: 20 }
                spacing: 18
                Icon {
                    name: routing.maneuverIcon || "straight"
                    size: 64
                    color: Theme.accent
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Label {
                        visible: !routing.arrived
                        numeric: true
                        text: routing.computing ? "" : page.distanceText(routing.distanceToTurn)
                        font.pixelSize: Theme.fontHero
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: routing.computing ? "Finding a new route" : routing.instruction
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
        Rectangle {
            visible: page.mapReady && page.navigating && !page.searching
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 16 }
            width: tripRow.implicitWidth + 36
            height: 72
            radius: Theme.radius
            color: Theme.panel
            border.width: Theme.border
            border.color: Theme.line
            RowLayout {
                id: tripRow
                anchors { fill: parent; leftMargin: 20; rightMargin: 10 }
                spacing: 18
                Column {
                    Label {
                        text: "Arrive " + page.arrivalText(routing.remainingTime)
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: page.durationText(routing.remainingTime) + ", " + page.distanceText(routing.remainingDistance)
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }
                TextButton { text: "End"; danger: true; implicitHeight: 52; onClicked: page.endRoute() }
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

        // ---- search: what you type, the matches, the keyboard ---------------
        Rectangle {
            visible: page.searching
            anchors.fill: parent
            radius: Theme.radius
            color: Theme.bg
            border.width: Theme.border
            border.color: Theme.line
            MouseArea { anchors.fill: parent }          // nothing underneath reacts

            ColumnLayout {
                anchors { fill: parent; margins: 16 }
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: Theme.radius
                        color: Theme.panel
                        border.width: Theme.border
                        border.color: Theme.accent
                        Icon {
                            id: glass
                            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                            name: "search"
                            size: 28
                            color: Theme.textDim
                        }
                        Label {
                            id: typed
                            anchors { left: glass.right; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            width: Math.min(implicitWidth, parent.width - 90)
                            clip: true
                            horizontalAlignment: implicitWidth > width ? Text.AlignRight : Text.AlignLeft
                            text: page.query
                            font.pixelSize: Theme.fontTitle
                        }
                        Label {
                            visible: page.query === ""
                            anchors { left: glass.right; leftMargin: 14; verticalCenter: parent.verticalCenter }
                            text: "Places, streets and businesses"
                            color: Theme.textDim
                            font.pixelSize: Theme.fontBody
                        }
                        Rectangle {                  // caret
                            x: typed.x + typed.width + 3
                            anchors.verticalCenter: parent.verticalCenter
                            width: 2
                            height: 34
                            color: Theme.accent
                            SequentialAnimation on opacity {
                                running: page.searching
                                loops: Animation.Infinite
                                NumberAnimation { to: 0; duration: 500; easing.type: Easing.InOutQuad }
                                NumberAnimation { to: 1; duration: 500; easing.type: Easing.InOutQuad }
                            }
                        }
                    }
                    TextButton { text: "Cancel"; implicitHeight: 64; onClicked: page.searching = false }
                }

                ListView {
                    id: results
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.query === "" ? page.saved : maps.results
                    delegate: Rectangle {
                        required property var modelData
                        width: results.width
                        height: 66
                        radius: Theme.radius
                        color: hit.pressed ? Theme.panelHi : "transparent"
                        Icon {
                            id: pinIcon
                            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            name: modelData.isHome ? "home" : "place"
                            size: 26
                            color: modelData.isHome ? Theme.accent : Theme.textDim
                        }
                        Column {
                            anchors { left: pinIcon.right; leftMargin: 14; right: dist.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            Label {
                                width: parent.width
                                elide: Text.ElideRight
                                text: modelData.name
                                font.pixelSize: Theme.fontBody
                            }
                            Label {
                                width: parent.width
                                elide: Text.ElideRight
                                text: modelData.label
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                        Label {
                            id: dist
                            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                            text: page.distanceText(modelData.distance !== undefined ? modelData.distance : page.distanceTo(modelData))
                            color: Theme.textDim
                            font.pixelSize: Theme.fontBody
                        }
                        TapHandler { id: hit; onTapped: page.choose(modelData) }
                    }
                    Label {
                        visible: results.count === 0
                        anchors { left: parent.left; top: parent.top; leftMargin: 12; topMargin: 12 }
                        text: page.query === "" ? "Works with no signal: everything in the map can be searched."
                                                : "Nothing in the map by that name"
                        width: parent.width - 24
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                Keyboard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 300
                    doneLabel: "Go"
                    doneEnabled: maps.results.length > 0 && page.query !== ""
                    onTyped: (ch) => page.query += ch
                    onBackspace: page.query = page.query.slice(0, -1)
                    onDone: page.choose(maps.results[0])
                }
            }
        }
    }
}

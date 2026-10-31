import QtQuick
import QtQuick.Layouts
import "../components"

// The Maps page, laid out like the car maps people already know (CarPlay,
// Android Auto) and sized to read from the driver's seat:
//
// - Browsing: the map follows the truck; "Where to?" sits top-left, with
//   one-tap Home and Work beside it once they're saved.
// - Searching: a panel down the left with the search box, Home, Work,
//   favourites, recent places and one-tap categories; the map stays visible
//   on the right. Typing brings up the keyboard across the bottom.
// - A picked place: the same panel shows it with keys to save it as Home,
//   Work or a favourite, the route already worked out (time, distance,
//   arrival) and a big Go at the bottom.
// - Driving a route: the next turn top-left, arrival bottom-left.
// - Always: the speed limit and speed on the right, one strip of map keys
//   bottom-right (zoom keys only appear after touching the map), and
//   Re-center when the map has been moved (automatic after 10 s while
//   driving a route).
//
// The map is light by day and dark at night (by the sun, or Settings).
Item {
    id: page
    objectName: "mapsPage"
    signal navigate(int index)

    // ---- state -----------------------------------------------------------------
    property var map: null              // the dashboard's one map engine (Main.qml)
    property bool mapReady: false
    property string problem: ""
    readonly property bool crashing: problem === "The map keeps crashing"   // MapView says it
    readonly property alias mapSlot: slot   // where Main.qml puts the map while this page shows
    readonly property real mapInsetLeft: panelShown || navigating ? panelWidth + 16 : 0
    onVisibleChanged: {
        if (visible) { if (hasMaps) maps.refresh() }
        else typing = false
    }
    onMapReadyChanged: {
        if (mapReady && pending) { var p = pending; pending = null; receive(p) }
        else if (mapReady && panel === "place" && place) map.call("showPlace(" + place.lon + "," + place.lat + ")")
    }

    readonly property bool hasMaps: typeof maps !== "undefined"
    readonly property bool hasFix: typeof gps !== "undefined" && gps.hasFix
    readonly property bool hasRouting: typeof routing !== "undefined"
    readonly property bool navigating: hasRouting && routing.active
    readonly property bool following: map !== null && map.following

    property string panel: ""          // "", "search", "results" or "place"
    property bool typing: false
    property string query: ""
    property string resultsTitle: ""
    property var place: null            // {name, label, lon, lat}
    readonly property int panelWidth: 500
    readonly property bool panelShown: panel !== "" && !navigating

    // Apple Maps' look for everything over the map: white cards by day, dark
    // grey ones at night, system blue for what's active, green Go, red End.
    readonly property bool dark: Theme.dark
    readonly property color cPanel: dark ? "#2c2c2e" : "#ffffff"
    readonly property color cPanelHi: dark ? "#3a3a3c" : "#f2f2f7"
    readonly property color cLine: dark ? "#48484a" : "#e5e5ea"
    readonly property color cText: dark ? "#ffffff" : "#1c1c1e"
    readonly property color cDim: dark ? "#98989f" : "#6c6c70"
    readonly property color cBlue: dark ? "#0a84ff" : "#007aff"
    readonly property color cGreen: dark ? "#30d158" : "#34c759"
    readonly property color cRed: dark ? "#ff453a" : "#ff3b30"
    readonly property color cBanner: dark ? "#2c2c2e" : "#1c1c1e"   // the next turn: dark in both
    readonly property color cBannerLow: dark ? "#3a3a3c" : "#2c2c2e"   // its "Then" strip
    readonly property int cRadius: 26


    // ---- Home, Work, favourites and recent places, saved between runs --------------
    function isPlace(p) {
        return !!p && typeof p === "object" && typeof p.lon === "number" && typeof p.lat === "number"
               && isFinite(p.lon) && isFinite(p.lat)
    }
    // A saved place, or a list of them (anything else in the file is dropped,
    // so a hand-edited or damaged setting can't put a blank row on the page).
    function loadJson(key, fallback) {
        if (typeof settings === "undefined") return fallback
        try {
            var v = JSON.parse(String(settings.get(key, JSON.stringify(fallback))))
            if (Array.isArray(fallback)) return Array.isArray(v) ? v.filter(isPlace) : fallback    // a list stays a list
            return isPlace(v) ? v : fallback
        } catch (e) { return fallback }
    }
    property var home: loadJson("homePlace", null)
    property var work: loadJson("workPlace", null)
    property var favourites: loadJson("favouritePlaces", [])    // in the order they were starred
    property var recents: loadJson("recentPlaces", [])
    function samePlace(a, b) {
        return !!a && !!b && a.name === b.name && Math.abs(a.lon - b.lon) < 1e-5 && Math.abs(a.lat - b.lat) < 1e-5
    }
    function plain(p) { return { name: p.name, label: p.label, lon: p.lon, lat: p.lat } }
    function isFavourite(p) { return favourites.some(f => samePlace(f, p)) }
    // Already shown as Home, Work or a favourite: no need to list it as recent too.
    function isSaved(p) { return samePlace(home, p) || samePlace(work, p) || isFavourite(p) }
    function remember(p) {
        var keep = plain(p)
        recents = [keep].concat(recents.filter(r => !samePlace(r, keep))).slice(0, 6)
        settings.set("recentPlaces", JSON.stringify(recents))
    }
    function toggleHome(p) {
        home = samePlace(home, p) ? null : plain(p)
        settings.set("homePlace", JSON.stringify(home))
    }
    function toggleWork(p) {
        work = samePlace(work, p) ? null : plain(p)
        settings.set("workPlace", JSON.stringify(work))
    }
    function toggleFavourite(p) {
        favourites = isFavourite(p) ? favourites.filter(f => !samePlace(f, p)) : favourites.concat([plain(p)])
        settings.set("favouritePlaces", JSON.stringify(favourites))
    }
    // The search panel lists each place once: Home and Work first, then
    // favourites, then the recent places that are none of those.
    readonly property var shownFavourites: favourites.filter(f => !samePlace(f, home) && !samePlace(f, work))
    readonly property var shownRecents: recents.filter(r => !isSaved(r)).slice(0, 3)

    // ---- distances -------------------------------------------------------------------
    function distanceTo(p) {
        if (!p || !hasFix) return -1
        var rad = Math.PI / 180
        var dx = (p.lon - gps.lon) * rad * Math.cos(gps.lat * rad) * 6371000
        var dy = (p.lat - gps.lat) * rad * 6371000
        return Math.sqrt(dx * dx + dy * dy)
    }

    // ---- what the controls do ------------------------------------------------------------
    function openSearch() { query = ""; panel = "search"; typing = false }
    function closePanel() {
        if (panel === "place") cancelPlace()
        panel = ""
        typing = false
    }
    function startTyping() { if (panel === "") panel = "search"; typing = true }
    onQueryChanged: if (typing) searchDelay.restart()
    Timer {
        id: searchDelay
        interval: 180
        onTriggered: if (page.query.trim() !== "")
            maps.search(page.query, page.hasFix ? gps.lon : 0, page.hasFix ? gps.lat : 0)
    }
    function searchCategory(key, label) {
        resultsTitle = label
        query = ""
        typing = false
        maps.searchNearby(key, hasFix ? gps.lon : -122.3321, hasFix ? gps.lat : 47.6062)
        panel = "results"
    }
    function showTyped() {
        // "Search" on the keyboard: the full list, keyboard away.
        resultsTitle = query
        typing = false
        panel = "results"
    }
    function choose(p) {
        place = p
        typing = false
        panel = "place"
        if (!isSaved(p)) remember(p)
        map.call("showPlace(" + p.lon + "," + p.lat + ")")
        if (hasRouting && routing.available && hasFix) routing.routeTo(p.name, p.lon, p.lat)
    }
    // A destination sent from the phone (Settings > Map > Send from phone).
    // While guiding it's offered, not taken: choose() would end the route.
    function receive(p) {
        if (navigating) offered = p
        else if (mapReady) choose(p)
        else pending = p
    }
    property var pending: null
    property var offered: null          // a phone place waiting for an answer on its card
    function takeOffer() {
        var p = offered
        offered = null
        // Guidance ends here, not in routeTo: choose() doesn't ask for a
        // route without the router or a fix, and the old one would carry on.
        routing.stop()
        if (mapReady) choose(p)
        else pending = p
    }
    function addOfferAsStop() {
        if (routing.addStop(offered.name, offered.lon, offered.lat)) offered = null
    }
    property string stopMessage: ""     // why a stop couldn't be added or skipped, for a few seconds
    Timer { id: stopMessageHide; interval: 4000; onTriggered: page.stopMessage = "" }
    onNavigatingChanged: if (!navigating && offered) {
        // The route ended meanwhile: the place is previewed as it would have been.
        var p = offered
        offered = null
        receive(p)
    }
    // After a restart the router works out the route that was on again
    // (backend/routing.py). Guidance that had started just carries on; a
    // place that was only being looked at comes back here, ready for Go.
    Connections {
        target: page.hasRouting ? routing : null
        function onResumed(name, lon, lat) {
            var p = { name: name, label: "", lon: lon, lat: lat }
            page.place = [page.home, page.work].concat(page.favourites, page.recents).find(r => page.samePlace(r, p)) || p
            page.typing = false
            page.panel = "place"
            if (page.mapReady) page.map.call("showPlace(" + lon + "," + lat + ")")
        }
        function onStopsFailed(text) {
            page.stopMessage = text
            stopMessageHide.restart()
        }
    }
    function cancelPlace() {
        if (hasRouting && !routing.active) routing.stop()
        place = null
        if (map) map.call("clearPlace()")
    }
    function go() {
        routing.go()
        panel = ""
    }
    function endRoute() {
        offered = null                  // ended on purpose: not a cue to preview the offer
        routing.stop()
        place = null
        map.call("clearPlace()")
    }

    // Zoom keys appear for a while after the map is touched.
    property bool showZoom: false
    Timer { id: zoomHide; interval: 10000; onTriggered: page.showZoom = false }
    // While driving a route, the map comes back to the truck by itself.
    Timer {
        id: autoRecenter
        interval: 10000
        running: page.navigating && !page.following && page.mapReady
        onTriggered: page.map.call("recenter()")
    }

    // ---- the map, in a framed card -------------------------------------------------------
    // The map, edge to edge; everything else floats over it.
    Item {
        id: frame
        anchors.fill: parent
        Rectangle { anchors.fill: parent; color: page.dark ? "#1a1b1d" : "#ebe7df" }   // the map's own ground
        Item { id: slot; anchors.fill: parent }
        Connections {
            target: page.map
            ignoreUnknownSignals: true
            function onTouched() {
                if (!page.visible) return
                page.showZoom = true
                zoomHide.restart()
                if (autoRecenter.running) autoRecenter.restart()
            }
        }

        // Until the map is drawn: what's happening, or what's missing.
        Column {
            visible: !page.mapReady
            anchors.centerIn: parent
            width: parent.width - 80
            spacing: 18
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "map"
                color: page.cDim
                size: 120
            }
            MapLabel {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                text: !page.hasMaps || !maps.webEngine ? "The map needs Qt WebEngine"
                      : !maps.ready ? "No map installed yet"
                      : page.crashing ? page.problem
                      : page.problem !== "" ? "The map didn't load"
                      : "Loading the map"
            }
            MapLabel {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: page.cDim
                font.pixelSize: Theme.fontBody
                text: !page.hasMaps || !maps.webEngine ? "Run deploy/setup-pi.sh on the Pi to install it"
                      : !maps.ready ? "Run deploy/maps/install-map.sh on the Pi to download the Seattle area"
                      : page.crashing ? "Trying again in a little while"
                      : page.problem !== "" ? page.problem
                      : maps.region
            }
        }

        // ================================================================================
        // Browsing: "Where to?"
        Sheet {
            id: whereTo
            visible: page.mapReady && !page.panelShown && !page.navigating && !page.typing
            x: 16; y: 16
            width: 440
            height: 100
            radius: page.cRadius
            color: page.cPanel
            scale: whereTap.pressed ? 0.98 : 1
            Behavior on scale { NumberAnimation { duration: 80 } }
            Row {
                anchors { left: parent.left; leftMargin: 26; verticalCenter: parent.verticalCenter }
                spacing: 18
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "search"; size: 44; color: page.cDim }
                MapLabel {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Where to?"
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
            }
            TapHandler { id: whereTap; onTapped: page.openSearch() }
        }
        // One tap Home or Work, beside it.
        Row {
            visible: whereTo.visible
            anchors { left: whereTo.right; leftMargin: 14; top: whereTo.top }
            spacing: 14
            SavedKey {
                visible: page.home !== null
                icon: "home"
                title: "Home"
                place: page.home
                onHit: page.choose(page.home)
            }
            SavedKey {
                visible: page.work !== null
                icon: "work"
                title: "Work"
                place: page.work
                onHit: page.choose(page.work)
            }
        }

        // ================================================================================
        // The panel down the left: search, results, a picked place.
        Sheet {
            id: sidePanel
            readonly property bool shown: page.mapReady && page.panelShown
            x: shown ? 16 : -width - 40
            opacity: shown ? 1 : 0
            visible: opacity > 0
            Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: 200 } }
            y: 16
            width: page.panelWidth
            height: (page.typing ? keyboard.y - 16 : parent.height) - 32
            radius: page.cRadius
            color: page.cPanel
            MouseArea { anchors.fill: parent }            // the map underneath doesn't react

            // ---- the header: search box (or a title), back and close ----
            RowLayout {
                id: header
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                spacing: 12

                PanelKey {
                    visible: page.panel === "results" || page.panel === "place"
                    icon: "back"
                    onHit: {
                        if (page.panel === "place") {
                            page.cancelPlace()
                            page.panel = page.resultsTitle !== "" ? "results" : "search"
                        } else {
                            page.resultsTitle = ""
                            page.panel = "search"
                        }
                    }
                }
                // The search box: tap to type.
                Rectangle {
                    visible: page.panel === "search"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
                    radius: 18
                    color: page.cPanelHi
                    border.width: page.typing ? 3 : 0
                    border.color: page.cBlue
                    Icon {
                        id: glass
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                        name: "search"
                        size: 38
                        color: page.cDim
                    }
                    MapLabel {
                        id: typed
                        anchors { left: glass.right; leftMargin: 12; verticalCenter: parent.verticalCenter }
                        width: Math.min(implicitWidth, parent.width - 90)
                        clip: true
                        horizontalAlignment: implicitWidth > width ? Text.AlignRight : Text.AlignLeft
                        text: page.query
                        font.pixelSize: Theme.fontTitle
                    }
                    MapLabel {
                        visible: page.query === ""
                        anchors { left: glass.right; leftMargin: 14; verticalCenter: parent.verticalCenter }
                        text: "Where to?"
                        color: page.cDim
                        font.pixelSize: Theme.fontTitle
                    }
                    Rectangle {                          // caret
                        visible: page.typing
                        x: typed.x + typed.width + 3
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: 44
                        color: page.cBlue
                        SequentialAnimation on opacity {
                            running: page.typing
                            loops: Animation.Infinite
                            NumberAnimation { to: 0; duration: 500; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1; duration: 500; easing.type: Easing.InOutQuad }
                        }
                    }
                    TapHandler { onTapped: page.startTyping() }
                }
                MapLabel {
                    visible: page.panel === "results"
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: page.resultsTitle
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                Item { visible: page.panel === "place"; Layout.fillWidth: true }
                PanelKey { icon: "close"; onHit: page.closePanel() }
            }

            // ---- search: Home, Work, favourites, recents, categories ----
            Flickable {
                visible: page.panel === "search" && !(page.typing && page.query !== "")
                anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: parent.bottom; margins: 14 }
                contentHeight: quick.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ColumnLayout {
                    id: quick
                    width: parent.width
                    spacing: 6
                    ResultRow {
                        visible: page.home !== null
                        icon: "home"
                        iconLit: true
                        title: "Home"
                        subtitle: page.home ? page.home.name : ""
                        trailing: Units.distanceText(page.distanceTo(page.home))
                        onHit: page.choose(page.home)
                    }
                    ResultRow {
                        visible: page.work !== null
                        icon: "work"
                        iconLit: true
                        title: "Work"
                        subtitle: page.work ? page.work.name : ""
                        trailing: Units.distanceText(page.distanceTo(page.work))
                        onHit: page.choose(page.work)
                    }
                    Heading { visible: page.shownFavourites.length > 0; text: "Favourites" }
                    Repeater {
                        model: page.shownFavourites
                        ResultRow {
                            icon: "star"
                            iconLit: true
                            title: modelData.name
                            subtitle: modelData.label || ""
                            trailing: Units.distanceText(page.distanceTo(modelData))
                            onHit: page.choose(modelData)
                        }
                    }
                    Heading { visible: page.shownRecents.length > 0; text: "Recent" }
                    Repeater {
                        model: page.shownRecents
                        ResultRow {
                            icon: "history"
                            title: modelData.name
                            subtitle: modelData.label || ""
                            trailing: Units.distanceText(page.distanceTo(modelData))
                            onHit: page.choose(modelData)
                        }
                    }
                    Heading { text: "Find nearby" }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        rowSpacing: 10
                        columnSpacing: 10
                        Repeater {
                            model: [
                                { key: "gas", label: "Gas" }, { key: "food", label: "Food" },
                                { key: "coffee", label: "Coffee" }, { key: "parking", label: "Parking" },
                                { key: "charging", label: "Charging" }, { key: "groceries", label: "Groceries" }
                            ]
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 100
                                radius: 18
                                color: catTap.pressed ? page.cLine : page.cPanelHi
                                scale: catTap.pressed ? 0.97 : 1
                                Behavior on scale { NumberAnimation { duration: 70 } }
                                Row {
                                    anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                                    spacing: 14
                                    Icon { anchors.verticalCenter: parent.verticalCenter; name: modelData.key; size: 40; color: page.cBlue }
                                    MapLabel {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.label
                                        font.pixelSize: Theme.fontBody
                                        font.weight: Font.DemiBold
                                    }
                                }
                                TapHandler { id: catTap; onTapped: page.searchCategory(modelData.key, modelData.label) }
                            }
                        }
                    }
                }
            }

            // ---- results (typed or a category) ----
            ListView {
                id: resultList
                visible: page.panel === "results" || (page.panel === "search" && page.typing && page.query !== "")
                anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: parent.bottom; margins: 14 }
                clip: true
                spacing: 6
                boundsBehavior: Flickable.StopAtBounds
                model: maps.results
                delegate: ResultRow {
                    required property var modelData
                    width: resultList.width
                    icon: page.kindIcon(modelData.kind)
                    title: modelData.name
                    subtitle: modelData.label
                    trailing: Units.distanceText(modelData.distance)
                    onHit: page.choose(modelData)
                }
                MapLabel {
                    visible: resultList.count === 0
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "Nothing by that name in the offline map"
                    color: page.cDim
                    font.pixelSize: Theme.fontBody
                }
            }

            // ---- a picked place: what it is, the route, and Go ----
            Item {
                visible: page.panel === "place" && page.place !== null
                anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: parent.bottom; margins: 20; topMargin: 6 }

                Column {
                    anchors { left: parent.left; right: parent.right; top: parent.top }
                    spacing: 8
                    MapLabel {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: page.place ? page.place.name : ""
                        font.pixelSize: Theme.fontTitle + 4
                        font.weight: Font.DemiBold
                    }
                    MapLabel {
                        width: parent.width
                        elide: Text.ElideRight
                        text: page.place ? page.place.label || "" : ""
                        color: page.cDim
                        font.pixelSize: Theme.fontBody
                    }
                    Item { width: 1; height: 6 }
                    // Keep it: Home, Work or a favourite (each lit when it is, tap to undo).
                    RowLayout {
                        width: parent.width
                        spacing: 10
                        SaveKey {
                            icon: "home"
                            label: "Home"
                            lit: page.samePlace(page.home, page.place)
                            onHit: page.toggleHome(page.place)
                        }
                        SaveKey {
                            icon: "work"
                            label: "Work"
                            lit: page.samePlace(page.work, page.place)
                            onHit: page.toggleWork(page.place)
                        }
                        SaveKey {
                            icon: page.isFavourite(page.place) ? "star" : "star_outline"
                            label: "Favourite"
                            lit: page.isFavourite(page.place)
                            onHit: page.toggleFavourite(page.place)
                        }
                    }
                    Item { width: 1; height: 12 }
                    // The route, worked out as soon as the place was picked.
                    MapLabel {
                        visible: page.hasRouting && routing.previewing
                        numeric: true
                        text: page.hasRouting ? Units.durationText(routing.remainingTime) : ""
                        font.pixelSize: Theme.fontHero
                    }
                    MapLabel {
                        visible: page.hasRouting && routing.previewing
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: page.hasRouting ? Units.distanceText(routing.remainingDistance) + ", arrive "
                                                + Units.arrivalText(routing.remainingTime) : ""
                        color: page.cDim
                        font.pixelSize: Theme.fontBody
                    }
                    MapLabel {
                        visible: page.hasRouting && routing.previewing && routing.stopCount > 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: page.hasRouting ? "Stops: " + routing.stops.map(s => s.name).join(", ") : ""
                        color: page.cDim
                        font.pixelSize: Theme.fontBody
                    }
                    // A ferry on the way, one row per crossing.
                    Repeater {
                        model: page.hasRouting && routing.previewing ? routing.ferries : []
                        Row {
                            width: parent.width
                            spacing: 8
                            Icon { anchors.verticalCenter: parent.verticalCenter; name: "ferry"; size: 32; color: page.cDim }
                            MapLabel {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 40
                                wrapMode: Text.WordWrap
                                text: "Ferry" + (modelData.name !== "Ferry" ? ": " + modelData.name : "") + (modelData.minutes > 0 ? ", " + modelData.minutes + " min" : "")
                                color: page.cDim
                                font.pixelSize: Theme.fontBody
                            }
                        }
                    }
                    // Being worked out again (a route option changed), or that failed.
                    MapLabel {
                        visible: page.hasRouting && routing.previewing && (routing.computing || routing.error !== "")
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: !page.hasRouting ? "" : routing.computing ? "Finding a route" : routing.error
                        color: page.cDim
                        font.pixelSize: Theme.fontBody
                    }
                    MapLabel {
                        visible: !page.hasRouting || !routing.previewing
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: page.cDim
                        font.pixelSize: Theme.fontBody
                        text: !page.hasRouting || !routing.available
                              ? Units.distanceText(page.distanceTo(page.place)) + " away. Directions need deploy/maps/install-routing.sh on the Pi."
                              : routing.computing ? "Finding a route"
                              : routing.error !== "" ? routing.error
                              : !page.hasFix ? "Waiting for the truck's position"
                              : ""
                    }
                }

                // Go, at the bottom where a thumb finds it: Apple's green.
                Rectangle {
                    visible: page.hasRouting && routing.previewing
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 116
                    radius: 22
                    color: goTap.pressed ? Qt.darker(page.cGreen, 1.2) : page.cGreen
                    scale: goTap.pressed ? 0.98 : 1
                    Behavior on scale { NumberAnimation { duration: 70 } }
                    MapLabel {
                        anchors.centerIn: parent
                        text: "Go"
                        color: "white"
                        font.pixelSize: Theme.fontHero
                        font.weight: Font.Bold
                    }
                    TapHandler { id: goTap; onTapped: page.go() }
                }
            }
        }

        // ================================================================================
        // Driving a route: the next turn, top-left, on a dark card in both
        // looks (as in Apple Maps): the biggest, clearest thing on screen.
        Sheet {
            id: turnCard
            readonly property bool shown: page.mapReady && page.navigating
            x: shown ? 16 : -width - 40
            opacity: shown ? 1 : 0
            visible: opacity > 0
            Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: 200 } }
            y: 16
            width: page.panelWidth
            height: turnContent.implicitHeight + 44 + (thenStrip.visible ? thenStrip.height : 0)
            Behavior on height { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
            color: page.cBanner
            clip: false

            // A new step fades in, so the change is noticed but not jarring.
            property string step: page.hasRouting ? routing.instruction : ""
            onStepChanged: stepFade.restart()
            NumberAnimation { id: stepFade; target: turnContent; property: "opacity"; from: 0.2; to: 1; duration: 350; easing.type: Easing.OutQuad }

            RowLayout {
                id: turnContent
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 22 }
                spacing: 18
                Icon {
                    Layout.alignment: Qt.AlignTop
                    name: page.hasRouting && routing.computing ? "refresh" : (page.hasRouting ? routing.maneuverIcon || "straight" : "straight")
                    size: 112
                    color: "white"
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    MapLabel {
                        visible: page.hasRouting && !routing.arrived && !routing.computing
                        numeric: true
                        text: page.hasRouting ? Units.distanceText(routing.distanceToTurn) : ""
                        color: "white"
                        font.pixelSize: Theme.fontHuge
                        font.weight: Font.DemiBold
                        lineHeight: 0.9
                    }
                    MapLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        text: !page.hasRouting ? "" : routing.computing ? "Finding a new route" : routing.instruction
                        color: "white"
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                }
            }

            // "Then ↰": a turn that comes right after this one.
            Item {
                id: thenStrip
                visible: page.hasRouting && routing.thenIcon !== "" && !routing.computing
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 76
                Rectangle {                              // rounded at the bottom only
                    anchors.fill: parent
                    radius: page.cRadius
                    color: page.cBannerLow
                }
                Rectangle {
                    anchors { left: parent.left; right: parent.right; top: parent.top }
                    height: page.cRadius
                    color: page.cBannerLow
                }
                Row {
                    anchors { left: parent.left; leftMargin: 28; verticalCenter: parent.verticalCenter }
                    spacing: 14
                    MapLabel {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Then"
                        color: "#ebebf5"
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: page.hasRouting && routing.thenIcon !== "" ? routing.thenIcon : "straight"
                        size: 52
                        color: "white"
                    }
                }
            }
            TapHandler { onTapped: routing.repeatLast() }    // say it again (Re-center is its own key)
        }

        // ... and the trip, bottom-left: arrival, time left, distance left.
        Sheet {
            id: tripCard
            readonly property bool shown: page.mapReady && page.navigating
            x: shown ? 16 : -width - 40
            opacity: shown ? 1 : 0
            visible: opacity > 0
            Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: 200 } }
            anchors { bottom: parent.bottom; bottomMargin: 16 }
            width: page.panelWidth
            height: 132 + (nextStop.visible ? nextStop.height + 8 : 0)
            Behavior on height { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
            readonly property real timeLeft: page.hasRouting ? routing.remainingTime : 0
            readonly property string distance: page.hasRouting ? Units.distanceText(routing.remainingDistance) : ""
            Item {
                id: nextStop
                readonly property string stopName: page.hasRouting ? routing.nextStopName : ""
                visible: stopName !== "" || page.stopMessage !== ""
                anchors { left: parent.left; right: parent.right; top: parent.top
                          leftMargin: 28; rightMargin: 16; topMargin: 8 }
                height: 60
                MapLabel {
                    anchors { left: parent.left; right: skip.visible ? skip.left : parent.right
                              rightMargin: 12; verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: page.stopMessage !== "" ? page.stopMessage : "Next stop: " + nextStop.stopName
                    color: page.cDim
                    font.pixelSize: Theme.fontBody
                }
                Rectangle {
                    id: skip
                    visible: nextStop.stopName !== ""
                    anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                    width: 104
                    radius: 18
                    color: skipTap.pressed ? page.cLine : page.cPanelHi
                    MapLabel {
                        anchors.centerIn: parent
                        text: "Skip"
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    TapHandler { id: skipTap; onTapped: routing.removeStop(0) }
                }
            }
            RowLayout {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                          leftMargin: 14; rightMargin: 16 }
                height: 132
                spacing: 0
                TripStat {
                    Layout.preferredWidth: 130
                    value: page.hasRouting ? Units.arrivalText(tripCard.timeLeft) : ""
                    label: "arrival"
                }
                TripStat {
                    readonly property int minutes: Math.max(1, Math.round(tripCard.timeLeft / 60))
                    value: minutes < 60 ? String(minutes)
                                        : Math.floor(minutes / 60) + ":" + String(minutes % 60).padStart(2, "0")
                    label: minutes < 60 ? "min" : "hr"
                }
                TripStat {
                    value: tripCard.distance.split(" ")[0]
                    label: tripCard.distance.split(" ")[1] || ""
                }
                Rectangle {                               // End: Apple's red
                    Layout.preferredWidth: 120
                    Layout.preferredHeight: 100
                    radius: 22
                    color: endTap.pressed ? Qt.darker(page.cRed, 1.2) : page.cRed
                    MapLabel {
                        anchors.centerIn: parent
                        text: "End"
                        color: "white"
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.Bold
                    }
                    TapHandler { id: endTap; onTapped: page.endRoute() }
                }
            }
        }

        // ================================================================================
        // The speed limit and the truck's speed, on the right.
        Column {
            visible: page.mapReady && page.hasFix && !page.typing
            anchors { right: parent.right; top: parent.top; margins: 16 }
            spacing: 12
            readonly property int limitKph: typeof road !== "undefined" ? road.speedLimit : 0
            // Shown in the local style: US sign in mph, round sign in km/h.
            readonly property int limit: Units.metric ? limitKph : Math.round(limitKph / 1.609344 / 5) * 5
            readonly property real speedNow: Units.speed(vehicle.speed)   // the same speed as Home
            readonly property bool over: limit > 0 && speedNow > limit + (Units.metric ? 8 : 5)

            Rectangle {                                   // US: SPEED LIMIT
                visible: parent.limit > 0 && !Units.metric
                width: 112; height: 140
                radius: 12
                color: "white"
                border.width: 5
                border.color: "black"
                Column {
                    anchors.centerIn: parent
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "SPEED"; font.pixelSize: 20; font.bold: true; color: "black" }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "LIMIT"; font.pixelSize: 20; font.bold: true; color: "black" }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: parent.parent.parent.limit; font.pixelSize: 60; font.bold: true; color: "black" }
                }
            }
            Rectangle {                                   // metric: red ring
                visible: parent.limit > 0 && Units.metric
                width: 124; height: 124
                radius: 62
                color: "white"
                border.width: 13
                border.color: "#d92b2b"
                Text { anchors.centerIn: parent; text: parent.parent.limit; font.pixelSize: 52; font.bold: true; color: "black" }
            }
            Sheet {                                       // speed now
                width: 112
                height: 108
                color: parent.over ? page.cRed : page.cPanel
                Column {
                    anchors.centerIn: parent
                    MapLabel {
                        anchors.horizontalCenter: parent.horizontalCenter
                        numeric: true
                        text: vehicle.speedKnown ? Math.round(parent.parent.parent.speedNow) : "—"
                        color: parent.parent.parent.over ? "white" : page.cText
                        font.pixelSize: Theme.fontReadout
                    }
                    MapLabel {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Units.speedUnit
                        color: parent.parent.parent.over ? "white" : page.cDim
                        font.pixelSize: Theme.fontSmall - 4
                    }
                }
            }
        }

        // ================================================================================
        // Map keys, bottom-right: one strip.
        Sheet {
            id: keys
            visible: page.mapReady && !page.typing
            anchors { right: parent.right; bottom: parent.bottom; margins: 16 }
            width: 104
            height: keyColumn.height
            Column {
                id: keyColumn
                width: parent.width
                PillKey { visible: page.showZoom; icon: "add"; onHit: { page.map.call("zoomIn()"); zoomHide.restart() } }
                PillKey { visible: page.showZoom; icon: "remove"; onHit: { page.map.call("zoomOut()"); zoomHide.restart() } }
                PillKey { visible: page.navigating; icon: "overview"; onHit: page.map.call("overview()") }
                PillKey {
                    visible: page.navigating && typeof voice !== "undefined" && voice.available
                    icon: typeof voice !== "undefined" && voice.enabled ? "volume" : "volume_off"
                    lit: typeof voice !== "undefined" && voice.enabled
                    onHit: voice.setEnabled(!voice.enabled)
                }
                PillKey {
                    icon: "navigation"
                    lit: page.following
                    divider: false
                    onHit: page.map.call("recenter()")
                }
            }
        }

        // A place sent from the phone while guiding: switch to it, add it, or keep going.
        Sheet {
            visible: page.offered !== null && page.navigating
            anchors { left: parent.left; leftMargin: page.panelWidth + 32      // between the turn card and the keys
                      bottom: parent.bottom; bottomMargin: 130 }
            width: parent.width - page.panelWidth - 32 - 140
            height: 190
            Column {
                anchors { fill: parent; margins: 20 }
                spacing: 12
                MapLabel {
                    width: parent.width
                    elide: Text.ElideRight
                    text: page.offered ? page.offered.name : ""
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                }
                RowLayout {
                    width: parent.width
                    height: 90
                    spacing: 12
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: thereTap.pressed ? Qt.darker(page.cBlue, 1.2) : page.cBlue
                        MapLabel {
                            anchors { fill: parent; margins: 8 }
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            lineHeight: 0.9
                            text: "Go there instead"
                            color: "white"
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.Bold
                        }
                        TapHandler { id: thereTap; onTapped: page.takeOffer() }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: stopTap.pressed ? page.cLine : page.cPanelHi
                        MapLabel {
                            anchors { fill: parent; margins: 8 }
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            lineHeight: 0.9
                            text: "Add as a stop"
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                        }
                        TapHandler { id: stopTap; onTapped: page.addOfferAsStop() }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: keepTap.pressed ? page.cLine : page.cPanelHi
                        MapLabel {
                            anchors { fill: parent; margins: 8 }
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            lineHeight: 0.9
                            text: "Keep going"
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                        }
                        TapHandler { id: keepTap; onTapped: page.offered = null }
                    }
                }
            }
        }

        // Re-center, when the map has been moved away from the truck.
        Sheet {
            readonly property bool shown: page.mapReady && page.hasFix && !page.following && !page.typing
                                          && !(page.panelShown && page.panel === "place")
            opacity: shown ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            anchors { horizontalCenter: parent.horizontalCenter; horizontalCenterOffset: page.panelShown || page.navigating ? (page.panelWidth + 16) / 2 : 0
                      bottom: parent.bottom; bottomMargin: 16 }
            width: recenterRow.implicitWidth + 56
            height: 100
            color: recenterTap.pressed ? page.cPanelHi : page.cPanel
            Row {
                id: recenterRow
                anchors.centerIn: parent
                spacing: 14
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "navigation"; size: 40; color: page.cBlue }
                MapLabel {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Re-center"
                    font.pixelSize: Theme.fontBody
                    font.weight: Font.DemiBold
                }
            }
            TapHandler { id: recenterTap; onTapped: page.map.call("recenter()") }
        }

        // The road you're on, bottom centre, while just following.
        Sheet {
            visible: page.mapReady && page.following && !page.navigating && page.map.road !== "" && !page.typing
                     && !page.panelShown
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 20 }
            width: Math.min(roadName.implicitWidth + 48, parent.width - 520)
            height: 72
            radius: height / 2
            MapLabel {
                id: roadName
                anchors.centerIn: parent
                width: Math.min(implicitWidth, parent.width - 48)
                elide: Text.ElideRight
                text: page.map ? page.map.road : ""
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
            }
        }

        // OpenStreetMap's licence asks for this to be visible on the map.
        MapLabel {
            visible: page.mapReady && !page.typing
            anchors { right: keys.left; rightMargin: 12; bottom: parent.bottom; bottomMargin: 8 }
            text: "© OpenStreetMap"
            color: page.cDim
            font.pixelSize: 18
        }

        // ================================================================================
        // Typing: the keyboard across the bottom.
        Keyboard {
            id: keyboard
            visible: page.typing
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 16 }
            height: 340
            doneLabel: "Search"
            doneEnabled: page.query.trim() !== ""
            onTyped: (ch) => page.query += ch
            onBackspace: page.query = page.query.slice(0, -1)
            onDone: page.showTyped()
        }
    }

    // ---- small parts -------------------------------------------------------------------
    // Text on the map: Overpass, like the map's own labels.
    component MapLabel: Label { font.family: Theme.mapFont; font.italic: false; color: page.cText }

    // A card floating over the map, on a soft shadow (a picture: the Pi's
    // Qt has no shadow effect, and this costs nothing to draw).
    component Sheet: Rectangle {
        radius: page.cRadius
        color: page.cPanel
        BorderImage {
            z: -1
            anchors { fill: parent; margins: -36; topMargin: -33; bottomMargin: -41 }
            source: "../assets/shadow.png"
            border { left: 64; right: 64; top: 64; bottom: 64 }
        }
    }

    // One figure on the trip card: the number, and what it is under it.
    component TripStat: Column {
        property string value
        property string label
        Layout.fillWidth: true
        Layout.preferredWidth: 100
        MapLabel {
            anchors.horizontalCenter: parent.horizontalCenter
            text: parent.value
            numeric: true
            font.pixelSize: 44
            font.weight: Font.DemiBold
        }
        MapLabel {
            anchors.horizontalCenter: parent.horizontalCenter
            text: parent.label
            color: page.cDim
            font.pixelSize: Theme.fontSmall
        }
    }
    function kindIcon(kind) {
        return ({ fuel: "gas", cafe: "coffee", restaurant: "food", fast_food: "food", parking: "parking",
                  charging_station: "charging", supermarket: "groceries", convenience: "groceries" })[kind] || "place"
    }

    // A saved place, one tap away on the map: icon, what it is, how far.
    component SavedKey: Item {
        id: saved
        property string icon
        property string title
        property var place: null
        signal hit()
        width: savedRow.implicitWidth + 48
        height: 100
        scale: savedTap.pressed ? 0.98 : 1
        Behavior on scale { NumberAnimation { duration: 80 } }
        Sheet { anchors.fill: parent }
        Row {
            id: savedRow
            anchors.centerIn: parent
            spacing: 14
            Icon { anchors.verticalCenter: parent.verticalCenter; name: saved.icon; size: 40; color: page.cBlue }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                MapLabel { text: saved.title; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold }
                MapLabel {
                    visible: text !== ""
                    text: Units.distanceText(page.distanceTo(saved.place))
                    color: page.cDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }
        TapHandler { id: savedTap; onTapped: saved.hit() }
    }

    // A heading in the search panel's list.
    component Heading: Item {
        property alias text: headingText.text
        Layout.fillWidth: true
        implicitHeight: headingText.implicitHeight + 20
        MapLabel {
            id: headingText
            anchors { left: parent.left; leftMargin: 6; bottom: parent.bottom; bottomMargin: 6 }
            font.pixelSize: Theme.fontBody
            font.weight: Font.Bold
        }
    }

    // A row in the panel's lists: icon, name, what it is, how far.
    component ResultRow: Rectangle {
        id: row
        property string icon: "place"
        property bool iconLit: false
        property string title
        property string subtitle
        property string trailing
        signal hit()
        Layout.fillWidth: true
        implicitHeight: 100
        radius: 16
        color: rowTap.pressed ? page.cPanelHi : "transparent"
        Icon {
            id: rowIcon
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            name: row.icon
            size: 38
            color: row.iconLit ? page.cBlue : page.cDim
        }
        Column {
            anchors { left: rowIcon.right; leftMargin: 16; right: rowTrail.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            MapLabel {
                width: parent.width
                elide: Text.ElideRight
                text: row.title
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
            }
            MapLabel {
                visible: text !== ""
                width: parent.width
                elide: Text.ElideRight
                text: row.subtitle
                color: page.cDim
                font.pixelSize: Theme.fontSmall
            }
        }
        MapLabel {
            id: rowTrail
            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            text: row.trailing
            color: page.cDim
            font.pixelSize: Theme.fontSmall
        }
        TapHandler { id: rowTap; onTapped: row.hit() }
    }

    // A key in the panel header.
    component PanelKey: Rectangle {
        id: pk
        property string icon
        property bool lit: false
        signal hit()
        Layout.preferredWidth: 96
        Layout.preferredHeight: 96
        radius: 48                                  // round, like Apple's
        color: pkTap.pressed ? page.cLine : pk.lit ? Qt.rgba(page.cBlue.r, page.cBlue.g, page.cBlue.b, 0.16) : page.cPanelHi
        Icon { anchors.centerIn: parent; name: pk.icon; size: 44; color: pk.lit ? page.cBlue : page.cText }
        TapHandler { id: pkTap; onTapped: pk.hit() }
    }

    // A save key under a picked place's name (Home, Work, Favourite): lit
    // while the place is saved that way, tap to save or undo.
    component SaveKey: Rectangle {
        id: sk
        property string icon
        property string label
        property bool lit: false
        signal hit()
        Layout.fillWidth: true
        Layout.preferredWidth: 100
        Layout.preferredHeight: 100
        radius: 18
        color: skTap.pressed ? page.cLine : sk.lit ? Qt.rgba(page.cBlue.r, page.cBlue.g, page.cBlue.b, 0.16) : page.cPanelHi
        Column {
            anchors.centerIn: parent
            spacing: 2
            Icon { anchors.horizontalCenter: parent.horizontalCenter; name: sk.icon; size: 40; color: sk.lit ? page.cBlue : page.cText }
            MapLabel {
                anchors.horizontalCenter: parent.horizontalCenter
                text: sk.label
                color: sk.lit ? page.cBlue : page.cText
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
            }
        }
        TapHandler { id: skTap; onTapped: sk.hit() }
    }

    // A key in the map's strip.
    component PillKey: Item {
        id: key
        property string icon
        property bool lit: false
        property bool divider: true
        signal hit()
        width: 104
        height: visible ? 100 : 0
        Rectangle {
            anchors { fill: parent; margins: 6 }
            radius: 18
            color: keyTap.pressed ? page.cPanelHi : "transparent"
        }
        Icon { anchors.centerIn: parent; name: key.icon; size: 46; color: key.lit ? page.cBlue : page.cText }
        Rectangle {
            visible: key.divider
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 14; bottomMargin: 0 }
            height: 2
            color: page.cLine
        }
        TapHandler { id: keyTap; onTapped: key.hit() }
    }
}

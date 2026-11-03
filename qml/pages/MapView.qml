import QtQuick
import QtWebEngine
import "../components"

// The map itself: MapLibre GL JS (web/map) in a WebEngineView, served by
// backend/maps.py. Kept in its own file and loaded by MapsPage's Loader, so
// a machine without Qt WebEngine still loads the rest of the dashboard.
// The page reports back through console messages that start with "baja:".
WebEngineView {
    id: web
    objectName: "mapView"
    anchors.fill: parent        // whichever slot Main.qml puts it in
    signal ready(int ms)
    signal failed(string message)
    signal benchDone(var result)
    signal touched()

    property string mode: "night"        // "day" or "night"
    property real insetLeft: 0           // dashboard pixels covered on the left by panels
    property real bearing: 0
    property bool following: false
    property bool outside: false          // the truck is off the offline map
    property string road: ""             // the road under the truck while following

    // Everything is drawn 1.7x (still sharp) so labels read from the
    // driver's seat; panel insets are converted to the page's pixels.
    zoomFactor: 1.7

    function call(js) { runJavaScript("window.baja && baja." + js) }
    // Several calls in one runJavaScript: each one is a round trip to the
    // render process and a parse of its source, so a fix's calls go together.
    function callAll(list) {
        if (list.length) runJavaScript("if (window.baja) { baja." + list.join("; baja.") + " }")
    }
    function sendInsets() { call("setInsets({ left: " + Math.round(insetLeft / zoomFactor) + " })") }
    // Only when the route or its state really changed, so a preview isn't
    // re-framed (and re-drawn in) by unrelated updates.
    property string routeKey: ""
    function syncRoute(force) {
        if (typeof routing === "undefined") return
        var shape = routing.shape
        var key = (routing.active ? "go" : routing.previewing ? "preview" : "none")
                  + ":" + shape.length + ":" + (shape.length ? shape[0].join(",") + shape[shape.length - 1].join(",") : "")
        if (key === routeKey && !force) return
        routeKey = key
        // showRoute and previewRoute start the page's segment over at 0.
        sentSegment = -1
        sentApproach = -1
        if (routing.active) call("showRoute(" + JSON.stringify(shape) + ")")
        else if (routing.previewing) call("previewRoute(" + JSON.stringify(shape) + ")")
        else call("clearRoute()")
    }
    // The last setApproach and setRouteAt values sent. The distance changes
    // by metres and the segment every few seconds, so most fixes repeat them.
    // -1 sends them again: the page has lost its state (reload, crash, route).
    property int sentApproach: -1
    property int sentSegment: -1
    function forgetSent() { sentApproach = -1; sentSegment = -1 }
    function sendPosition() {
        var list = []
        if (typeof gps !== "undefined" && gps.hasFix)
            list.push("setPosition(" + gps.lon + "," + gps.lat + "," + gps.heading + "," + gps.speed + ")")
        if (typeof routing !== "undefined" && routing.active) {
            var approach = Math.round(routing.distanceToTurn)
            if (approach !== sentApproach) { list.push("setApproach(" + approach + ")"); sentApproach = approach }
            if (routing.segment !== sentSegment) { list.push("setRouteAt(" + routing.segment + ")"); sentSegment = routing.segment }
        }
        callAll(list)
    }

    // Set once, not bound: a day/night change restyles the running map.
    Component.onCompleted: url = maps.pageUrl + "?mode=" + mode
    onModeChanged: call("setMode('" + mode + "')")
    onInsetLeftChanged: sendInsets()
    backgroundColor: mode === "day" ? "#d9d5cc" : "#14160f"
    settings.showScrollBars: false
    settings.focusOnNavigationEnabled: false
    settings.javascriptCanAccessClipboard: false

    onJavaScriptConsoleMessage: (level, message, line, source) => {
        if (message.indexOf("baja:") === 0) {
            var m = JSON.parse(message.slice(5))
            if (m.kind === "ready") {
                // The look may have been set before the page could hear it.
                web.call("setMode('" + web.mode + "')")
                web.outside = m.outside === true    // the page says if the truck is already out
                web.sendInsets(); web.ready(m.ms); web.forgetSent(); web.sendPosition(); web.syncRoute(true)
                stableTimer.restart()       // up for a minute: the crashes are over
            }
            else if (m.kind === "follow") web.following = m.on
            else if (m.kind === "outside") web.outside = m.on
            else if (m.kind === "road") web.road = m.name
            else if (m.kind === "touched") web.touched()
            else if (m.kind === "error") console.warn("map:", m.message)
            else if (m.kind === "bearing") web.bearing = m.bearing
            else if (m.kind === "bench") web.benchDone(m)
            else if (m.kind === "info") console.log("map:", JSON.stringify(m))
        } else if (level === WebEngineView.ErrorMessageLevel) {
            console.warn("map page:", message, "(" + source + ":" + line + ")")
        }
    }
    onLoadingChanged: (request) => {
        if (request.status === WebEngineView.LoadStartedStatus || request.status === WebEngineView.LoadSucceededStatus)
            forgetSent()            // a new page (or a reload) has none of the last values
        if (request.status === WebEngineView.LoadFailedStatus)
            web.failed(request.errorString)
        else if (request.status === WebEngineView.LoadSucceededStatus)
            reloadTimer.stop()      // already reloaded by something else (a map update)
    }
    // If the page's process dies, start it again rather than leave a blank
    // map, waiting longer after each crash in a row: a page that dies on
    // every load (a GPU or memory problem, a bad tile file) would otherwise
    // get a new renderer every second, forever. After a few the Maps page is
    // told. A crash stops counting as "in a row" once the map has drawn and
    // stayed up for a minute.
    property int crashes: 0
    readonly property var reloadAfter: [1000, 5000, 30000, 180000]     // ms; the last repeats
    readonly property int crashesToGiveUp: 3
    // Every crash, so the page can stop showing a map that isn't there.
    signal crashed()
    function terminationName(status) {
        return status === WebEngineView.NormalTerminationStatus ? "exited"
             : status === WebEngineView.AbnormalTerminationStatus ? "exited abnormally"
             : status === WebEngineView.CrashedTerminationStatus ? "crashed"
             : status === WebEngineView.KilledTerminationStatus ? "was killed"
             : "status " + status
    }
    onRenderProcessTerminated: (status, code) => {
        crashes++
        stableTimer.stop()
        forgetSent()
        var wait = reloadAfter[Math.min(crashes, reloadAfter.length) - 1]
        console.warn("map: page process " + terminationName(status) + " (exit code " + code + "), "
                     + crashes + " in a row, reloading in " + wait / 1000 + " s")
        crashed()
        if (crashes >= crashesToGiveUp) failed("The map keeps crashing")
        reloadTimer.interval = wait
        reloadTimer.restart()
    }
    Timer { id: reloadTimer; onTriggered: web.reload() }
    Timer { id: stableTimer; interval: 60000; onTriggered: web.crashes = 0 }

    // A route previewed, started or ended: draw it; follow once it starts.
    Connections {
        target: typeof routing !== "undefined" ? routing : null
        property bool wasActive: false
        function onChanged() {
            web.syncRoute()
            if (routing.active && !wasActive) web.call("recenter()")
            wasActive = routing.active
        }
    }

    // The truck's position, once per new fix (not on satellite or receiver
    // status updates, which would reset the map's fix age and glide).
    Connections {
        target: typeof gps !== "undefined" ? gps : null
        function onFixChanged() { web.sendPosition() }
    }
    // A fix going stale brings no new fix, so send the position once more:
    // its speed is 0 now, which stops the map's glide.
    readonly property bool gpsStale: typeof gps !== "undefined" && gps !== null && gps.stale
    onGpsStaleChanged: if (gpsStale) sendPosition()

    // New map data (Settings > Map > Update): load it.
    Connections {
        target: maps
        property string build: maps.build
        function onChanged() {
            if (maps.build !== build && maps.ready) { build = maps.build; web.reload() }
        }
    }
}

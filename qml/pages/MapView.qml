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
    property string road: ""             // the road under the truck while following

    // Everything is drawn 1.7x (still sharp) so labels read from the
    // driver's seat; panel insets are converted to the page's pixels.
    zoomFactor: 1.7

    function call(js) { runJavaScript("window.baja && baja." + js) }
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
        if (routing.active) call("showRoute(" + JSON.stringify(shape) + ")")
        else if (routing.previewing) call("previewRoute(" + JSON.stringify(shape) + ")")
        else call("clearRoute()")
    }
    function sendPosition() {
        if (typeof gps !== "undefined" && gps.hasFix)
            call("setPosition(" + gps.lon + "," + gps.lat + "," + gps.heading + "," + gps.speed + ")")
        if (typeof routing !== "undefined" && routing.active)
            call("setApproach(" + Math.round(routing.distanceToTurn) + ")")
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
                web.sendInsets(); web.ready(m.ms); web.sendPosition(); web.syncRoute(true)
            }
            else if (m.kind === "follow") web.following = m.on
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
        if (request.status === WebEngineView.LoadFailedStatus)
            web.failed(request.errorString)
    }
    // If the page's process dies, start it again rather than leave a blank map.
    onRenderProcessTerminated: (status, code) => {
        console.warn("map: page process ended (" + status + "), reloading")
        reloadTimer.start()
    }
    Timer { id: reloadTimer; interval: 1000; onTriggered: web.reload() }

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

    // The truck's position, about once a second.
    Connections {
        target: typeof gps !== "undefined" ? gps : null
        function onChanged() { web.sendPosition() }
    }

    // New map data (Settings > Map > Update): load it.
    Connections {
        target: maps
        property string build: maps.build
        function onChanged() {
            if (maps.build !== build && maps.ready) { build = maps.build; web.reload() }
        }
    }
}

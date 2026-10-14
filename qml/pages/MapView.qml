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
    signal ready(int ms)
    signal failed(string message)
    signal benchDone(var result)
    property real bearing: 0
    property bool following: false

    // The dashboard's colours, which the map derives its palette from.
    function themeTokens() {
        return {
            bg: String(Theme.bg), panel: String(Theme.panel), panelHi: String(Theme.panelHi),
            line: String(Theme.line), text: String(Theme.text), textDim: String(Theme.textDim),
            accent: String(Theme.accent), warn: String(Theme.warn), ok: String(Theme.ok)
        }
    }
    function call(js) { runJavaScript("window.baja && baja." + js) }
    function sendPosition() {
        if (typeof gps !== "undefined" && gps.hasFix)
            call("setPosition(" + gps.lon + "," + gps.lat + "," + gps.heading + "," + gps.speed + ")")
    }

    // Set once, not bound: a style change recolours the running map
    // (Connections below) instead of reloading the page.
    Component.onCompleted: url = maps.pageUrl + "?theme=" + encodeURIComponent(JSON.stringify(themeTokens()))
    backgroundColor: Theme.bg
    // Draw the whole map 1.4x larger (still sharp): the stock label sizes are
    // too small to read at arm's length on the 8" panel.
    zoomFactor: 1.4
    settings.showScrollBars: false
    settings.focusOnNavigationEnabled: false
    settings.javascriptCanAccessClipboard: false

    onJavaScriptConsoleMessage: (level, message, line, source) => {
        if (message.indexOf("baja:") === 0) {
            var m = JSON.parse(message.slice(5))
            if (m.kind === "ready") { web.ready(m.ms); web.sendPosition() }
            else if (m.kind === "follow") web.following = m.on
            else if (m.kind === "error") console.warn("map:", m.message)
            else if (m.kind === "bearing") web.bearing = m.bearing
            else if (m.kind === "bench") web.benchDone(m)
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
    Connections {
        target: Theme
        function onStyleChanged() { web.call("setTheme(" + JSON.stringify(web.themeTokens()) + ")") }
    }
}

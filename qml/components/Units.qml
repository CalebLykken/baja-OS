pragma Singleton
import QtQuick

// Display units and the clock format, picked in Settings and saved. The
// vehicle data stays in what the truck reports (mph, °F, psi); readouts and
// gauges convert through these helpers.
QtObject {
    property bool metric: false
    property bool clock24: false

    function speed(mph) { return metric ? mph * 1.609344 : mph }
    readonly property string speedUnit: metric ? "km/h" : "mph"

    function temp(f) { return metric ? (f - 32) * 5 / 9 : f }
    readonly property string tempUnit: metric ? "°C" : "°F"

    function boost(psi) { return metric ? psi * 0.0689476 : psi }
    readonly property string boostUnit: metric ? "bar" : "psi"
    readonly property int boostDecimals: metric ? 2 : 1

    // "6:25" in 12-hour (no AM/PM, like a car clock) or "18:25" in 24-hour.
    // (Qt's "h:mm" alone is 24-hour, so 12-hour is done by hand.)
    function timeText(date) {
        if (clock24) return Qt.formatTime(date, "H:mm")
        var h = date.getHours() % 12 || 12
        var m = date.getMinutes()
        return h + ":" + (m < 10 ? "0" : "") + m
    }

    // Distances for directions: feet then miles, or metres then kilometres.
    function distanceText(m) {
        if (m < 0) return ""
        if (metric)
            return m < 1000 ? Math.round(m / 10) * 10 + " m" : (m / 1000).toFixed(m < 10000 ? 1 : 0) + " km"
        var mi = m / 1609.34
        return mi < 0.1 ? Math.round(m * 3.281 / 50) * 50 + " ft" : mi.toFixed(mi < 10 ? 1 : 0) + " mi"
    }
    function durationText(s) {
        var min = Math.max(1, Math.round(s / 60))
        return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min"
    }
    function arrivalText(s) { return timeText(new Date(Date.now() + s * 1000)) }
}

pragma Singleton
import QtQuick

// Display units and the clock format, picked in Settings and saved. The
// vehicle data stays in what the truck reports (mph, °F, psi); readouts and
// gauges convert through these helpers.
QtObject {
    property bool metric: false
    property bool clock24: false
    property string appearance: "auto"  // "auto" (light by day, dark at night), "light" or "dark"

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
    // Decimals follow the rounded value, so 9.96 mi reads "10 mi", not "10.0 mi".
    // Metres switch to km once they would round to 1000 m.
    function distanceText(m) {
        if (m < 0) return ""
        if (metric) {
            if (Math.round(m / 10) * 10 < 1000) return Math.max(10, Math.round(m / 10) * 10) + " m"
            var km = Math.round(m / 100) / 10
            return (km < 10 ? km.toFixed(1) : km.toFixed(0)) + " km"
        }
        var mi = m / 1609.34
        if (mi < 0.1) return Math.max(50, Math.round(m * 3.281 / 50) * 50) + " ft"
        var miles = Math.round(mi * 10) / 10
        return (miles < 10 ? miles.toFixed(1) : miles.toFixed(0)) + " mi"
    }
    // Whole hours drop the minutes: "1 h", "1 h 5 min".
    function durationText(s) {
        var min = Math.max(1, Math.round(s / 60))
        if (min < 60) return min + " min"
        var rest = min % 60
        return Math.floor(min / 60) + " h" + (rest ? " " + rest + " min" : "")
    }
    // The clock time you get there, with " tomorrow" or " in N days" when the
    // trip ends on a later calendar day, so an overnight leg is not ambiguous.
    // Days are counted from local midnight to midnight, so a daylight-saving
    // change (a 23 or 25 hour day) still counts as one day. "from" is for tests.
    function arrivalText(s, from) {
        var now = from === undefined ? new Date() : from
        var t = new Date(now.getTime() + s * 1000)
        var days = Math.round((new Date(t.getFullYear(), t.getMonth(), t.getDate())
                               - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000)
        var day = days === 0 ? "" : days === 1 ? " tomorrow" : " in " + days + " days"
        return timeText(t) + day
    }
}

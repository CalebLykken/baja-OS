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

    readonly property string timeFormat: clock24 ? "H:mm" : "h:mm"
}

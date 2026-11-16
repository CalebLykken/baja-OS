import QtQuick

// Four small status icons for the foot of the nav rail: GPS fix, phone
// connected, Wi-Fi online, car answering. Lit (the status green) when it is
// so, dim otherwise. Pure bindings: nothing runs while nothing changes, and
// it takes no taps.
Grid {
    id: strip
    columns: 2
    spacing: 8

    readonly property bool gpsOk: typeof gps !== "undefined" && gps.hasFix
    readonly property bool phoneOk: typeof bluetooth !== "undefined" && bluetooth.deviceName !== ""
    readonly property bool wifiOk: typeof network !== "undefined" && network.online
    readonly property bool carOk: typeof vehicle !== "undefined" && vehicle.live

    Icon {
        objectName: "gps"
        size: 28
        name: strip.gpsOk ? "gps_fixed" : "gps_off"
        color: strip.gpsOk ? Theme.ok : Theme.textDim
        opacity: strip.gpsOk ? 1 : 0.5
    }
    Icon {
        objectName: "phone"
        size: 28
        name: "bluetooth"
        color: strip.phoneOk ? Theme.ok : Theme.textDim
        opacity: strip.phoneOk ? 1 : 0.5
    }
    Icon {
        objectName: "wifi"
        size: 28
        name: strip.wifiOk ? "wifi" : "wifi_off"
        color: strip.wifiOk ? Theme.ok : Theme.textDim
        opacity: strip.wifiOk ? 1 : 0.5
    }
    Icon {
        objectName: "car"
        size: 28
        name: "engine_check"
        color: strip.carOk ? Theme.ok : Theme.textDim
        opacity: strip.carOk ? 1 : 0.5
    }
}

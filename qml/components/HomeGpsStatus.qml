import QtQuick

// A small status pill over Home's map: why the map isn't moving. Shown only when
// the receiver is missing, still finding satellites, or has lost the sky; hidden
// with a good fix and during the demo drive. No MouseArea, so taps still reach
// the tile underneath.
Rectangle {
    id: pill
    readonly property bool haveGps: typeof gps !== "undefined" && gps !== null
    readonly property string message: {
        if (!haveGps || gps.source === "demo" || (gps.hasFix && !gps.stale))
            return ""
        if (!gps.receiverConnected)
            return "No GPS receiver"
        if (!gps.hasFix)
            return "Finding satellites" + (gps.satellites > 0 ? " · " + gps.satellites : "")
        return gps.stale ? "GPS signal lost" : ""
    }
    readonly property bool shown: message !== ""

    // Keeps the last words while it fades out.
    property string shownText: ""
    onMessageChanged: if (message !== "") shownText = message

    objectName: "homeGpsStatus"
    width: pillLabel.implicitWidth + 40
    height: 56
    radius: Theme.radius
    color: Theme.panel
    border.width: Theme.border
    border.color: Theme.line
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220 } }

    Label {
        id: pillLabel
        objectName: "homeGpsStatusText"
        anchors.centerIn: parent
        text: pill.shownText
        font.pixelSize: Theme.fontSmall
        font.weight: Font.DemiBold
    }
}

import QtQuick
import QtQuick.Layouts

// The key-off countdown: the seconds left as a big number with a bar that
// drains beside it, readable at a glance while climbing out of the truck.
// The bar turns to the warning colour for the last few seconds. It only
// changes when `seconds` does (once a second); nothing here animates or polls.
ColumnLayout {
    id: countdown
    property int seconds: 0
    property int total: 10          // the length of the countdown; see keyOffPrompt in Main.qml
    property int warnAt: 3          // at or below this many seconds the bar warns

    spacing: 8

    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: 10
        Label {
            objectName: "countNumber"
            numeric: true
            text: Math.max(0, countdown.seconds)
            font.pixelSize: Theme.fontHuge
            font.weight: Theme.numWeight
            color: countdown.seconds <= countdown.warnAt ? Theme.warn : Theme.text
        }
        Label {
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: 14
            text: "s"
            font.pixelSize: Theme.fontSmall
            color: Theme.textDim
        }
    }
    ProgressBar {
        objectName: "countBar"
        Layout.fillWidth: true
        height: 10
        radius: 5
        value: countdown.total > 0 ? Math.max(0, countdown.seconds) / countdown.total : 0
        fill: countdown.seconds <= countdown.warnAt ? Theme.warn : Theme.accent
    }
}

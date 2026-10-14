import QtQuick
import QtQuick.Layouts

// A settings card that grows to fit what's in it: an optional sentence-case
// heading, then its content stacked with even spacing.
Card {
    id: sec
    default property alias content: body.data
    property alias spacing: body.spacing

    implicitHeight: body.implicitHeight + body.anchors.topMargin + 20

    ColumnLayout {
        id: body
        anchors {
            left: parent.left; right: parent.right; top: parent.top
            leftMargin: 20; rightMargin: 20
            topMargin: sec.heading !== "" ? 50 : 20
        }
        spacing: 14
    }
}

import QtQuick
import QtQuick.Layouts
import "../components"

// Placeholder settings. Nothing here is wired to hardware yet.
Item {
    id: page
    signal navigate(int index)

    property int brightness: 80
    property bool metric: false

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: "Brightness"

            RowLayout {
                anchors { fill: parent; leftMargin: 20; rightMargin: 20; topMargin: 36 }
                spacing: 16
                IconButton { glyph: "−"; size: 60; onClicked: page.brightness = Math.max(10, page.brightness - 10) }
                ProgressBar { Layout.fillWidth: true; height: 10; radius: 5; value: page.brightness / 100 }
                Text {
                    Layout.preferredWidth: 64
                    horizontalAlignment: Text.AlignRight
                    text: page.brightness + "%"
                    color: Theme.text
                    font.pixelSize: Theme.fontBody
                }
                IconButton { glyph: "+"; size: 60; onClicked: page.brightness = Math.min(100, page.brightness + 10) }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: "Units"

            Row {
                anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                spacing: 12
                Repeater {
                    model: [{ label: "Imperial (mph, °F)", metric: false }, { label: "Metric (km/h, °C)", metric: true }]
                    Rectangle {
                        readonly property bool selected: page.metric === modelData.metric
                        width: unitText.width + 48
                        height: 56
                        radius: 28
                        color: selected ? Theme.accent : Theme.panelHi
                        Text {
                            id: unitText
                            anchors.centerIn: parent
                            text: modelData.label
                            color: parent.selected ? Theme.bg : Theme.text
                            font.pixelSize: Theme.fontBody - 2
                        }
                        TapHandler { onTapped: page.metric = modelData.metric }
                    }
                }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            heading: "About"

            Column {
                anchors { left: parent.left; top: parent.top; leftMargin: 20; topMargin: 52 }
                spacing: 8
                Text { text: "Baja OS"; color: Theme.text; font.pixelSize: Theme.fontTitle; font.weight: Font.DemiBold }
                Text { text: "2005 Subaru Baja Turbo carputer"; color: Theme.textDim; font.pixelSize: Theme.fontBody }
                Text {
                    text: demoMode ? "Running on simulated vehicle and media data" : "Live data"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
            }
        }
    }
}

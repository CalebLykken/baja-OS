import QtQuick
import QtQuick.Layouts
import "../components"

// Settings. Brightness drives the panel; units and about are placeholders.
Item {
    id: page
    signal navigate(int index)

    // Saved between runs; QSettings hands booleans back as strings.
    property bool metric: typeof settings !== "undefined"
                          && String(settings.get("metric", "false")) === "true"
    onMetricChanged: if (typeof settings !== "undefined") settings.set("metric", metric ? "true" : "false")

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: display.hardware ? "Brightness" : "Brightness (software dim)"

            RowLayout {
                anchors { fill: parent; leftMargin: 20; rightMargin: 20; topMargin: 36 }
                spacing: 16
                IconButton { glyph: "−"; size: 60; onClicked: display.setBrightness(display.brightness - 10) }

                // Tap or drag anywhere along the bar; the tall hit area is
                // easier to land on in a moving car than the 10 px bar.
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ProgressBar {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                        height: 10
                        radius: 5
                        value: display.brightness / 100
                    }
                    MouseArea {
                        anchors.fill: parent
                        function apply(x) { display.setBrightness(Math.round(100 * x / width)) }
                        onPressed: (mouse) => apply(mouse.x)
                        onPositionChanged: (mouse) => apply(mouse.x)
                    }
                }

                Label {
                    Layout.preferredWidth: 64
                    horizontalAlignment: Text.AlignRight
                    text: display.brightness + "%"
                    color: Theme.text
                    font.pixelSize: Theme.fontBody
                }
                IconButton { glyph: "+"; size: 60; onClicked: display.setBrightness(display.brightness + 10) }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            heading: "Style"

            Row {
                anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter; verticalCenterOffset: 14 }
                spacing: 12
                Repeater {
                    model: Theme.styleNames
                    Rectangle {
                        readonly property bool selected: Theme.style === modelData
                        width: styleText.width + 48
                        height: 56
                        radius: 28
                        color: selected ? Theme.accent : Theme.panelHi
                        Label {
                            id: styleText
                            anchors.centerIn: parent
                            text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                            color: parent.selected ? Theme.bg : Theme.text
                            font.pixelSize: Theme.fontBody - 2
                        }
                        TapHandler { onTapped: Theme.style = modelData }
                    }
                }
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
                        Label {
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
                Label { text: "Baja OS"; color: Theme.text; font.pixelSize: Theme.fontTitle; font.weight: Font.DemiBold }
                Label { text: "2005 Subaru Baja Turbo carputer"; color: Theme.textDim; font.pixelSize: Theme.fontBody }
                Label {
                    text: demoMode ? "Running on simulated vehicle and media data" : "Live data"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                }
            }
        }
    }
}

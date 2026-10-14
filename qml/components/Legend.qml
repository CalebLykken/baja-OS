import QtQuick

// An instrument legend: the small caps label on gauges, readouts and the nav
// rail (RPM, BOOST, HOME). The only place caps are used (docs/DESIGN.md).
Label {
    color: Theme.textDim
    font.pixelSize: Theme.fontLegend
    font.weight: Font.DemiBold
    font.letterSpacing: Theme.legendTracking
    font.capitalization: Font.AllUppercase
}

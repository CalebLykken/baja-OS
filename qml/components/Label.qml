import QtQuick

// Text in the active style's font. Use this instead of Text so a style
// change reaches every label.
Text {
    property bool numeric: false   // big numbers use the style's number font

    color: Theme.text
    font.family: numeric ? Theme.numFont : Theme.font
    font.italic: numeric && Theme.numItalic
}

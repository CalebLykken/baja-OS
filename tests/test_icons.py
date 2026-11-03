"""Guards the icon path table move: Icon.qml reads IconPaths.js, which must
hold every path the QML uses. Plain text checks, so this runs without PyQt6."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml"
ICON_QML = QML / "components" / "Icon.qml"
ICON_PATHS = QML / "components" / "IconPaths.js"

# Icon.qml held 75 path entries before the table moved out. The table must not shrink.
MIN_ICON_PATHS = 75

# Paths start with M or a relative m (`gas` is "m19.77 ..."), so accept either.
KEY_RE = re.compile(r'^\s*([a-z_0-9]+):\s*"[Mm]', re.M)
# `icon: "x"` covers Main.qml's nav model, IconButton/TextButton/PillKey users and
# `property string icon: "place"` defaults. Empty defaults (`icon: ""`) do not match.
ICON_PROP_RE = re.compile(r'\bicon:\s*"([a-z_0-9]+)"')
ICON_BLOCK_RE = re.compile(r'\bIcon\s*\{')
NAME_LITERAL_RE = re.compile(r'\bname:\s*([^\n;]*)')
STRING_RE = re.compile(r'"([a-z_0-9]+)"')
# String literals used in comparisons (`parent.src === "phone"`) are not icon names.
COMPARE_RE = re.compile(r'(===|!==|==|!=)\s*"[^"]*"')


def icon_table_keys():
    return KEY_RE.findall(ICON_PATHS.read_text(encoding="utf-8"))


def icon_blocks(text):
    """Yield the text of each `Icon { ... }` block (brace-matched)."""
    for m in ICON_BLOCK_RE.finditer(text):
        depth = 0
        for i in range(m.end() - 1, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield text[m.start():i + 1]
                    break


def used_icon_names():
    names = {}
    for path in sorted(QML.rglob("*.qml")):
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        for name in ICON_PROP_RE.findall(text):
            names.setdefault(name, rel)
        for block in icon_blocks(text):
            for expr in NAME_LITERAL_RE.findall(block):
                expr = COMPARE_RE.sub("", expr)
                for name in STRING_RE.findall(expr):
                    names.setdefault(name, rel)
    return names


class IconPathTableTests(unittest.TestCase):

    def test_table_has_no_fewer_entries_than_before(self):
        keys = icon_table_keys()
        self.assertGreaterEqual(len(keys), MIN_ICON_PATHS)

    def test_table_keys_are_unique(self):
        keys = icon_table_keys()
        self.assertEqual(len(keys), len(set(keys)), "duplicate icon name in IconPaths.js")

    def test_icon_qml_no_longer_builds_table(self):
        text = ICON_QML.read_text(encoding="utf-8")
        self.assertNotIn("paths: ({", text)
        self.assertIn('import "IconPaths.js" as IconPaths', text)
        self.assertIn("IconPaths.paths[name]", text)

    def test_table_is_a_shared_library_script(self):
        text = ICON_PATHS.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(".pragma library"))
        self.assertIn("var paths = {", text)

    def test_every_icon_name_used_in_qml_is_in_table(self):
        keys = set(icon_table_keys())
        missing = {n: where for n, where in used_icon_names().items() if n not in keys}
        self.assertEqual(missing, {}, "icon names used in QML but missing from IconPaths.js")


if __name__ == "__main__":
    unittest.main()

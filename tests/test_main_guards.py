"""Main.qml must load when a backend object is missing (the screenshot tool,
a bench Mac and the tests don't have every backend). Each use of a backend
name is checked: the same object, or an enclosing one, has to say
`typeof name` in its own text (not inside a nested block), so a guard on one
handler does not cover its neighbours. The allow-list holds the few uses
that are only reachable through a guarded object, with the reason."""
import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "qml" / "Main.qml"

BACKENDS = ("display", "settings", "bluetooth", "keyOff", "updater", "system",
            "vehicle", "media", "routing", "phone", "gps", "network", "maps")

# "name.member" -> why it may be used without its own typeof check.
ALLOW = {
    "system.powerOff":
        "the shutdown button of keyOffPrompt; that prompt only shows while the "
        "keyOff countdown runs, and keyOff is guarded in the prompt's own properties",
}

# Comments and string contents become spaces (newlines kept), so positions
# and line numbers still match the file.
TOKEN = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|//[^\n]*|/\*.*?\*/', re.S)


def blank(m):
    return re.sub(r"[^\n]", " ", m.group(0))


def own_text(src, start, end):
    """The text of a block from its opening brace up to `end`, leaving out the
    contents of nested blocks."""
    out, depth = [], 0
    for ch in src[start + 1:end]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


class MainBackendGuards(unittest.TestCase):
    def setUp(self):
        self.src = TOKEN.sub(blank, QML.read_text())
        # Each "{" with the position of its matching "}".
        self.blocks = {}
        stack = []
        for i, ch in enumerate(self.src):
            if ch == "{":
                stack.append(i)
            elif ch == "}" and stack:
                self.blocks[stack.pop()] = i

    def unguarded(self):
        found = []
        for name in BACKENDS:
            for m in re.finditer(r"(?<![\w.])%s\.(\w+)" % name, self.src):
                p = m.start()
                enclosing = sorted(o for o, c in self.blocks.items() if o < p < c)
                guarded = any(re.search(r"typeof\s+%s\b" % name, own_text(self.src, o, p))
                              for o in enclosing)
                key = "%s.%s" % (name, m.group(1))
                if not guarded and key not in ALLOW:
                    line = self.src.count("\n", 0, p) + 1
                    found.append("line %d: %s" % (line, key))
        return found

    def test_every_backend_use_is_guarded(self):
        self.assertEqual(self.unguarded(), [])

    def test_allow_list_entries_are_still_used(self):
        for key in ALLOW:
            self.assertRegex(self.src, r"(?<![\w.])%s\s*\(" % re.escape(key),
                             "allow-list entry %s is no longer used" % key)

    def test_dimming_layer_waits_for_display(self):
        src = QML.read_text()
        self.assertIn('visible: typeof display !== "undefined" && !display.hardware', src)
        self.assertIn('opacity: visible ? (1 - display.brightness / 100) * 0.85 : 0', src)

    def test_units_handlers_wait_for_settings(self):
        src = QML.read_text()
        for handler in ("onMetricChanged", "onClock24Changed", "onAppearanceChanged"):
            body = src.split("function %s()" % handler, 1)[1].split("\n", 1)[0]
            self.assertIn('typeof settings !== "undefined"', body, handler)


if __name__ == "__main__":
    unittest.main()

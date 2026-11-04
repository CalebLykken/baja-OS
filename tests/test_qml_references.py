"""MapsPage.qml refers to its root as `page`; a `page.x` with no declaration
is silently undefined in QML (no error, just a wrong value), which is how the
map's ground stayed light at night."""
import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "qml" / "pages" / "MapsPage.qml"


class MapsPageRootReferences(unittest.TestCase):
    def test_every_page_member_is_declared_on_the_root(self):
        src = QML.read_text()
        declared = set(re.findall(r"^\s*(?:readonly\s+)?property\s+\S+\s+(\w+)", src, re.M))
        declared.update(re.findall(r"^\s*(?:function|signal)\s+(\w+)", src, re.M))
        used = set(re.findall(r"\bpage\.(\w+)", src))
        # Members every Item has anyway.
        builtin = {"visible", "width", "height", "x", "y", "opacity", "enabled", "parent"}
        self.assertEqual(sorted(used - declared - builtin), [])

    def test_map_ground_follows_the_theme(self):
        src = QML.read_text()
        self.assertNotIn("page.dark", src)
        self.assertIn("Theme.dark ?", src)


class MainMilestoneToast(unittest.TestCase):
    def test_milestone_skips_only_while_splash_is_visible(self):
        src = (QML.parent.parent / "Main.qml").read_text()
        body = src.split("function onMilestone", 1)[1].split("}", 1)[0]
        self.assertNotIn("showSplash", body)
        self.assertIn("splash.visible", body)
        self.assertRegex(src, r"Splash\s*\{\s*id:\s*splash\b")


if __name__ == "__main__":
    unittest.main()

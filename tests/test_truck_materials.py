"""The Truck page's glass and bright-metal materials: tools/convert_truck.py
(MATERIALS) and the generated BajaModel.qml must agree, and the glass must
stay opaque, back-face culled, rough and dim so it can't glint in streaks."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def script_materials():
    # Read the dict without importing the script (it runs on import and needs PIL).
    tree = ast.parse((ROOT / "tools/convert_truck.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MATERIALS":
            return ast.literal_eval(node.value)
    raise AssertionError("MATERIALS not found")


def qml_materials():
    text = (ROOT / "qml/assets/truck/BajaModel.qml").read_text()
    blocks = {}
    for block in re.findall(r"    PrincipledMaterial \{.*?\n    \}", text, flags=re.S):
        name = re.search(r'objectName: "([^"]+)"', block)[1]
        blocks[name] = dict(re.findall(r"\n\s+(\w+): ([^\n]+)", block))
    return blocks


def same(a, b):
    a, b = a.strip(), b.strip()
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return a == b


class TruckMaterialsTest(unittest.TestCase):
    def test_qml_matches_script(self):
        qml = qml_materials()
        for prefix, props in script_materials().items():
            found = [n for n in qml if n.startswith(prefix)]
            self.assertTrue(found, prefix)
            for name in found:
                for key, value in props.items():
                    self.assertIn(key, qml[name], f"{name}.{key}")
                    self.assertTrue(same(qml[name][key], value), f"{name}.{key}: {qml[name][key]} != {value}")

    def test_glass_is_culled_rough_dim_and_opaque(self):
        qml = qml_materials()
        for prefix in ("clearglass", "windowglass", "darkglass"):
            found = [n for n in qml if n.startswith(prefix)]
            self.assertTrue(found, prefix)
            for name in found:
                m = qml[name]
                self.assertEqual(m["cullMode"], "PrincipledMaterial.BackFaceCulling", name)
                self.assertGreaterEqual(float(m["roughness"]), 0.7, name)
                self.assertLessEqual(float(m["specularAmount"]), 0.1, name)
                self.assertEqual(m["alphaMode"], "PrincipledMaterial.Opaque", name)

    def test_small_bright_parts_stay_metal_but_rough(self):
        qml = qml_materials()
        for name in ("mirror.163", "chrome.173"):
            self.assertEqual(float(qml[name]["metalness"]), 1, name)
            self.assertGreaterEqual(float(qml[name]["roughness"]), 0.08, name)


if __name__ == "__main__":
    unittest.main()

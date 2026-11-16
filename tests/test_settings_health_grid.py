"""Off-Pi checks for the Health grid on Settings' System section: six cells,
no empty filler, the Pi supply reading in its own cell, and warnings for low
storage and memory. Reads the source, so it runs without PyQt.

    python3 -m unittest tests.test_settings_health_grid
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


def health_grid():
    start = PAGE.index('heading: "Health"')
    grid = PAGE.index("GridLayout {", start)
    end = PAGE.index("\n                }\n", grid)
    return PAGE[grid:end]


class HealthGridTest(unittest.TestCase):
    def test_grid_has_six_readouts_and_no_empty_cell(self):
        grid = health_grid()
        self.assertEqual(grid.count("Readout {"), 6)
        self.assertNotIn("Item {", grid)

    def test_every_readout_is_one_preferred_column(self):
        grid = health_grid()
        self.assertEqual(grid.count("Layout.preferredWidth: 1"), 6)

    def test_pi_supply_cell_shows_dash_without_unit_when_unknown(self):
        grid = health_grid()
        start = grid.index('label: "Pi supply"')
        cell = grid[start:grid.index("}", start)]
        self.assertIn('value: powerLog.supply < 0 ? "–" : powerLog.supply.toFixed(2)', cell)
        self.assertIn('unit: powerLog.supply < 0 ? ""', cell)
        self.assertIn('"V, low " + powerLog.lowest.toFixed(2)', cell)
        self.assertIn("warning: powerLog.supply >= 0 && powerLog.lowest < 4.8", cell)

    def test_separate_supply_label_is_gone(self):
        self.assertNotIn("Pi supply \" + powerLog", PAGE)

    def test_storage_warns_only_with_a_real_reading(self):
        grid = health_grid()
        start = grid.index('label: "Storage free"')
        cell = grid[start:grid.index("}\n", grid.index("warning:", start))]
        self.assertIn("warning: system.diskTotal > 0 && system.diskFree < 2", cell)

    def test_memory_warns_above_ninety_percent(self):
        grid = health_grid()
        start = grid.index('label: "Memory used"')
        cell = grid[start:grid.index("}\n", grid.index("warning:", start))]
        self.assertIn("warning: system.memTotal > 0 && system.memUsed > 0.9 * system.memTotal", cell)


if __name__ == "__main__":
    unittest.main()

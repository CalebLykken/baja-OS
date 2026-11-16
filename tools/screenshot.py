"""Screenshots of the real dashboard, off-screen, for checking a UI change.

Starts main.py with demo data (no splash), then for each style and
appearance asked for, shows each page, waits for it to settle and saves it:

    QT_QPA_PLATFORM=offscreen python tools/screenshot.py OUTDIR
    python tools/screenshot.py OUTDIR --pages 0,4 --styles trail,rally --appearance night
    python tools/screenshot.py OUTDIR --eval "media.togglePlay()" --wait 2500

Pages: 0 Home, 1 Music, 2 Maps, 3 Gauges, 4 Truck, 5 Settings. Files are
OUTDIR/<style>-<appearance>-<page>.png. The Maps page needs Qt WebEngine and
the Truck page Qt Quick 3D with a GPU, so off-screen they may come out blank;
everything else draws as on the Pi (the Pi runs Qt 6.8).

--eval runs a line of JavaScript in the window's QML context before the
first shot (e.g. to open a panel); --qml-eval is the same, per page.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["home", "music", "maps", "gauges", "truck", "settings"]


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    p.add_argument("--pages", default="0,1,3,5", help="comma-separated page numbers (default 0,1,3,5)")
    p.add_argument("--styles", default="", help="comma-separated styles (default: the saved one)")
    p.add_argument("--appearance", default="night", help="day, night or both (default night)")
    p.add_argument("--size", default="1280x800")
    p.add_argument("--wait", type=int, default=1500, help="ms to let each page settle")
    p.add_argument("--eval", default="", help="JavaScript to run once, before the first shot")
    return p.parse_args()


def main():
    args = parse()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in args.size.split("x"))
    pages = [int(v) for v in args.pages.split(",") if v.strip()]
    styles = [s for s in args.styles.split(",") if s] or [None]
    looks = ["day", "night"] if args.appearance == "both" else [args.appearance]

    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    sys.argv = ["main.py", "--demo", "--no-splash"]
    import main as dashboard
    from PyQt6.QtCore import QMetaObject, Q_ARG, QTimer, Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlExpression

    shots = [(s, a, p) for s in styles for a in looks for p in pages]
    real_exec = QGuiApplication.exec

    def call(win, name, value):
        QMetaObject.invokeMethod(win, name, Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", value))

    def run(app):
        from PyQt6 import sip
        from PyQt6.QtQuick import QQuickWindow
        # PyQt hands top-level windows back as plain QWindow: cast to reach grabWindow.
        win = next((sip.cast(x, QQuickWindow) for x in QGuiApplication.topLevelWindows()
                    if x.inherits("QQuickWindow")), None)
        if win is None:
            print("screenshot: no window", file=sys.stderr)
            app.exit(1)
            return
        win.resize(w, h)
        if args.eval:
            from PyQt6.QtQml import qmlContext
            expr = QQmlExpression(qmlContext(win), win, args.eval)
            expr.evaluate()
            if expr.hasError():
                print("screenshot: --eval failed:", expr.error().toString(), file=sys.stderr)
        todo = list(shots)

        def next_shot():
            if not todo:
                app.quit()
                return
            style, look, page = todo[0]
            if style:
                call(win, "setStyle", style)
            call(win, "setAppearance", look)
            call(win, "showPage", page)
            QTimer.singleShot(args.wait, save)

        def save():
            style, look, page = todo.pop(0)
            name = f"{style or 'current'}-{look}-{page}-{PAGES[page] if page < len(PAGES) else page}.png"
            win.grabWindow().save(str(out / name))
            print("saved", out / name, flush=True)
            next_shot()

        next_shot()

    def exec_(*_):
        app = QGuiApplication.instance()
        QTimer.singleShot(2500, lambda: run(app))   # backends and QML settle first
        return real_exec()                           # static in PyQt6

    QGuiApplication.exec = exec_
    code = dashboard.main()
    os._exit(code or 0)


if __name__ == "__main__":
    main()

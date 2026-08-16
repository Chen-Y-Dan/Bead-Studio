"""Entry point for ``python -m beadstudio`` and the frozen PyInstaller exe.

Besides launching the GUI, this module hosts two headless flags:
``--list-brands``, a self-test that proves the palette data bundled via
PyInstaller ``--add-data`` resolves correctly under ``sys._MEIPASS``, and
``--version``, which prints the beadstudio version (from ``__version__``)
for packaged-app version checks.
"""

import sys


def _list_brands_selftest() -> int:
    """Print the count of bundled palette brands, then exit.

    Only runs when ``--list-brands`` is on the command line; normal GUI
    startup ignores it. The count must match the engine's 21 brands — any
    other value means the palette data is missing in the bundle.

    A ``--windowed`` exe has no console (``sys.stdout`` is ``None``), so
    the report is written BOTH to stdout (works under ``python -m
    beadstudio``) and to ``beadstudio_selftest.txt`` in the current
    directory (readable when the frozen exe is run headlessly). Exit code
    is 0 only when all 21 brands are found.
    """
    from beadstudio.core.palette import list_brands

    report = f"list-brands={len(list_brands())}\n"
    try:
        sys.stdout.write(report)
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 — windowed exe has no stdout
        pass
    try:
        with open("beadstudio_selftest.txt", "w", encoding="utf-8") as fh:
            fh.write(report)
    except Exception:  # noqa: BLE001 — best-effort artifact
        pass
    return 0 if report == "list-brands=21\n" else 1


def _version_report() -> int:
    """Print ``BeadStudio <version>`` to stdout, then exit 0.

    The frozen ``--windowed`` exe has no console (``sys.stdout`` is
    ``None``), so the write is wrapped in try/except; the exit code alone
    is the reliable signal in that mode.
    """
    from beadstudio import __version__

    report = f"BeadStudio {__version__}\n"
    try:
        sys.stdout.write(report)
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 — windowed exe has no stdout
        pass
    return 0


def main() -> int:
    """Launch the GUI, or run a headless flag when one is passed."""
    if "--list-brands" in sys.argv:
        return _list_brands_selftest()
    if "--version" in sys.argv:
        return _version_report()
    from beadstudio.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())

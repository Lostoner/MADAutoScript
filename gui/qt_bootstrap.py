"""Configure the bundled Qt before creating QApplication.

PyQt5/Qt 5.15.2 may expose a lossy compiled plugin prefix on Windows when
the virtual environment lives under a Unicode directory. Resolve the real
installed wheel path and pass it to Qt through its Unicode API instead.
No system environment or installed application settings are modified.
"""
from pathlib import Path
import os

_dll_directory_handles = []


def configure_qt():
    import PyQt5
    from PyQt5.QtCore import QCoreApplication

    qt_root = Path(PyQt5.__file__).resolve().parent / "Qt5"
    plugin_dir = qt_root / "plugins"
    platform = "qwindows.dll" if os.name == "nt" else None
    if not plugin_dir.is_dir() or (platform and not (plugin_dir / "platforms" / platform).is_file()):
        raise RuntimeError(f"Qt 插件不完整：{plugin_dir}")
    if os.name == "nt" and not _dll_directory_handles:
        _dll_directory_handles.append(os.add_dll_directory(str(qt_root / "bin")))
    # The Windows offscreen plugin uses a font directory rather than the
    # native Windows font database. The wheel carries no fonts. Point test
    # rendering at the existing system fonts without copying/bundling them.
    if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
        if fonts.is_dir():
            os.environ.setdefault("QT_QPA_FONTDIR", str(fonts))
    QCoreApplication.setLibraryPaths([str(plugin_dir)])
    return plugin_dir

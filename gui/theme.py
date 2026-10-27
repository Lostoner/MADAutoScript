"""M0 theme adapter derived from BAAS gui/util/config_gui.py.

Source: pur1fying/blue_archive_auto_script@1110e88df5955df277737ea9717869b9ca88362b
GPL-3.0-only. Semantic colors are retained with new workspace surfaces; persistence belongs to the
new AppSettingsRepository, never the original BAAS global config singleton.
"""
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPalette, QFont
from PyQt5.QtWidgets import QWidget
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor


def ui_font(size=14, weight=QFont.Normal):
    font = QFont()
    font.setFamilies(['Segoe UI', 'Microsoft YaHei UI'])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.PreferAntialias)
    return font


def typography(widget, size=14, bold=False):
    widget.setProperty('fontSize', size)
    widget.setProperty('fontBold', bold)
    widget.setFont(ui_font(size, QFont.DemiBold if bold else QFont.Normal))
    return widget


def apply_typography(root):
    # Fluent controls set their own fonts during construction/theme changes.
    for widget in [root, *root.findChildren(QWidget)]:
        widget.setFont(ui_font(widget.property('fontSize') or 14,
                              QFont.DemiBold if widget.property('fontBold') else QFont.Normal))


COLOR_THEME = {
    'Light': {
        'background': '#eeffffff', 'background_hover': '#e0f7fa',
        'text': '#333333', 'outline': '#ffffff', 'border': '#eecccccc',
        'background__success': '#d4edda', 'background__warning': '#fff3cd',
        'background__error': '#f8d7da', 'background__info': '#d1ecf1',
        'text__success': '#155724', 'text__warning': '#856404',
        'text__error': '#721c24', 'text__info': '#0c5460', 'text__gray': '#666666',
        'border__success': '#c3e6cb', 'border__warning': '#ffeeba',
        'border__error': '#f5c6cb', 'border__info': '#bee5eb',
    },
    'Dark': {
        'background': '#44333333', 'background_hover': '#555555',
        'text': '#ffffff', 'outline': '#333333', 'border': '#ee555555',
        'background__success': '#1e3d2f', 'background__warning': '#3d3620',
        'background__error': '#402626', 'background__info': '#1f3a40',
        'text__success': '#a6e3b0', 'text__warning': '#ffd97a',
        'text__error': '#f28b82', 'text__info': '#80d4ea', 'text__gray': '#bbbbbb',
        'border__success': '#3a5f4b', 'border__warning': '#5f5635',
        'border__error': '#6a3a3a', 'border__info': '#34656a',
    },
}

# Upstream COLOR_THEME contains translucent overlays. A standalone window
# also needs opaque surfaces, otherwise native/offscreen palettes can supply
# a white background beneath dark-theme text and translucent Fluent controls.
SURFACE_THEME = {
    'Light': {'window': '#f9faf9', 'page': '#f9faf9', 'input': '#ffffff', 'card': '#ffffff',
              'line': '#e5eae6', 'accent': '#008846', 'muted': '#7b857f', 'selected': '#edf7f0'},
    'Dark': {'window': '#1c211e', 'page': '#1c211e', 'input': '#242b26', 'card': '#242b26',
             'line': '#354038', 'accent': '#64c58a', 'muted': '#a1aea5', 'selected': '#2c4132'},
}
COLOR_THEME['Light'].update(text='#252d28', text__gray='#7b857f')
COLOR_THEME['Dark'].update(text='#e9efeb', text__gray='#a1aea5')


class ThemeManager(QObject):
    changed = pyqtSignal()

    def __init__(self, name='system', parent=None):
        super().__init__(parent)
        self.name = name
        self.apply(name)

    @property
    def colors(self):
        return COLOR_THEME['Dark' if isDarkTheme() else 'Light']

    @property
    def surfaces(self):
        return SURFACE_THEME['Dark' if isDarkTheme() else 'Light']

    def apply_surface(self, widget, role='page'):
        """Set palette backing without replacing a Fluent control's QSS."""
        palette = widget.palette()
        palette.setColor(QPalette.Window, QColor(self.surfaces[role]))
        palette.setColor(QPalette.Base, QColor(self.surfaces['input']))
        palette.setColor(QPalette.WindowText, QColor(self.colors['text']))
        palette.setColor(QPalette.Text, QColor(self.colors['text']))
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)

    def apply_scroll_surface(self, area, content):
        """Opaque, scoped backgrounds; child Fluent widgets retain their QSS."""
        color = self.surfaces['page']
        area.setStyleSheet(f'QScrollArea#{area.objectName()} {{background-color: {color}; border: none;}}')
        content.setObjectName(f'{area.objectName()}Content')
        content.setStyleSheet(f'QWidget#{content.objectName()} {{background-color: {color};}}')
        for widget in (area, area.viewport(), content):
            self.apply_surface(widget)

    def apply(self, name):
        themes = {'system': Theme.AUTO, 'light': Theme.LIGHT, 'dark': Theme.DARK}
        if name not in themes:
            raise ValueError(f'Unknown theme: {name}')
        self.name = name
        setTheme(themes[name], save=False)
        setThemeColor(QColor(self.surfaces['accent']), save=False)
        self.changed.emit()

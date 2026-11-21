"""Offline presentation assets; selection values still belong to the game catalog."""
from functools import lru_cache
from html import escape
import json

from PyQt5.QtCore import Qt, QSize, QUrl
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QListView
from qfluentwidgets import FluentIcon as FIF

from core.paths import REPO_ROOT
from gui.theme import ui_font


@lru_cache(maxsize=1)
def thumbnail_catalog():
    return json.loads((REPO_ROOT/'src/selection_catalog.json').read_text('utf-8'))


def thumbnail_entry(kind, key):
    if kind == 'stages':
        key = key.split('-')[0] if key.startswith('normal:') else key.rsplit(':', 1)[0]
    return thumbnail_catalog()[kind].get(key, {})


@lru_cache(maxsize=256)
def thumbnail_icon(kind, key):
    entry = thumbnail_entry(kind, key)
    path = entry.get('file') or (thumbnail_catalog()['fallback'] if kind == 'characters' else '')
    if not path:
        return QIcon()
    if kind == 'places':
        # The original 4:1 banners are too thin at list size. Crop only their
        # displayed thumbnail to 2:1; the hover preview keeps the full image.
        pixmap = QPixmap(str(REPO_ROOT/path))
        if pixmap.isNull(): return QIcon()
        pixmap = pixmap.scaled(128, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        return QIcon(pixmap.copy((pixmap.width()-128)//2, (pixmap.height()-64)//2, 128, 64))
    return QIcon(str(REPO_ROOT/path))


def thumbnail_tooltip(kind, key, title):
    entry = thumbnail_entry(kind, key)
    text = '<b>' + escape(title) + '</b>'
    if not entry or entry.get('status') == 'unmapped':
        return text + ('<br>头像待补；保留原选择值。' if kind == 'characters' else '')
    url = QUrl.fromLocalFile(str(REPO_ROOT/entry['file'])).toString()
    width = 240 if kind == 'places' else 120
    text += f'<br><img src="{escape(url, quote=True)}" width="{width}">'
    if kind == 'stages': text += '<br>所属区域缩略图；关卡以名称和编号为准。'
    return text


def decorate_item(item, kind, key, title=None):
    item.setIcon(thumbnail_icon(kind, key))
    item.setFont(ui_font('caption'))
    item.setToolTip(thumbnail_tooltip(kind, key, title or item.text()))


def prepare_thumbnail_combo(combo, size=QSize(32, 32), *, prefix=''):
    combo.setView(QListView(combo))
    combo.setIconSize(size)
    combo.setMaxVisibleItems(8)
    combo.setSizeAdjustPolicy(combo.AdjustToMinimumContentsLengthWithIcon)
    combo.view().setTextElideMode(Qt.ElideNone)
    combo.setProperty('thumbnailPrefix', prefix)
    combo.currentIndexChanged.connect(lambda _: _update_combo_tooltip(combo))


def _update_combo_tooltip(combo):
    prefix = combo.property('thumbnailPrefix') or ''
    combo.setToolTip((escape(prefix) + '<br>' if prefix else '') +
                    (combo.currentData(Qt.ToolTipRole) or escape(combo.currentText())))


def add_thumbnail_choice(combo, kind, key, title=None):
    title = title or key
    combo.addItem(thumbnail_icon(kind, key), title, key)
    index = combo.count()-1
    combo.setItemData(index, thumbnail_tooltip(kind, key, title), Qt.ToolTipRole)
    combo.setItemData(index, QSize(0, max(36, combo.iconSize().height()+8)), Qt.SizeHintRole)
    if index == combo.currentIndex(): _update_combo_tooltip(combo)


def action_icon(key):
    """Abstract actions use the existing Fluent icon set, not unrelated game art."""
    icon = {
        'mad.stamina_claim': FIF.LEAF, 'mad.flara_sweep': FIF.PEOPLE,
        'mad.normal_sweep': FIF.FLAG, 'mad.material_sweep': FIF.TILES,
        'mad.procurement_sweep': FIF.SYNC, 'mad.gold_shop': FIF.SHOPPING_CART,
        'mad.dating': FIF.HEART, 'mad.mail': FIF.MAIL, 'mad.claim_all': FIF.CHECKBOX,
        'activity': FIF.FLAG, 'pass': FIF.CALENDAR, 'mall': FIF.SHOPPING_CART,
        'tasks': FIF.CHECKBOX, 'mail': FIF.MAIL,
    }[key]
    return icon.icon()

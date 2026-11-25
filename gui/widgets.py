"""Small BAAS widgets extracted without the game-specific UI import graph.

Source: pur1fying/blue_archive_auto_script@1110e88df5955df277737ea9717869b9ca88362b
gui/util/customized_ui.py, GPL-3.0-only. The three class implementations
below are retained unchanged, with only their import context extracted.
"""
from typing import Union

from PyQt5.QtCore import QEvent, Qt, pyqtSignal, QMimeData
from PyQt5.QtGui import QColor, QIcon, QDrag, QPainter
from PyQt5.QtWidgets import QLabel, QFrame, QHBoxLayout, QVBoxLayout, QToolButton, QMenu, QAction, QApplication, QSizePolicy
from qfluentwidgets import ExpandSettingCard, FluentIcon as FIF, LineEdit, CheckBox, ListWidget
from gui.theme import typography
from gui.motion import Reveal, Transition
from gui.reorder_feedback import set_drag_badge


class FuncLabel(QLabel):
    button_clicked_signal = pyqtSignal()

    def __init__(self, parent=None):
        super(FuncLabel, self).__init__(parent)

    def mouseReleaseEvent(self, QMouseEvent):
        self.button_clicked_signal.emit()

    def connect_customized_slot(self, func):
        self.button_clicked_signal.connect(func)


class ClickFocusLineEdit(LineEdit):
    """
    Custom LineEdit that does not focus unless clicked
    This is to prevent the LineEdit from stealing focus
    from the parent widget when the user strike a hover
    on the LineEdit. This is useful when the LineEdit is
    used in a TableWidget, and the user wants to click on
    the parent widget to select a row.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.installEventFilter(self)

    def eventFilter(self, a0, a1):
        if a1.type() == QEvent.MouseButtonPress:
            self.setFocus()
        return super().eventFilter(a0, a1)


class BAASSettingCard(ExpandSettingCard):
    def __init__(self, icon: Union[str, QIcon, FIF], title: str, content: str = None, parent=None):
        super().__init__(icon, title, content, parent)
        self._adjustViewSize()
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in [Qt.Key_Up, Qt.Key_Down]:
                return True
        return super().eventFilter(obj, event)


class ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ''
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, max(0, self.width())))

    def resizeEvent(self, event):
        self._elide()
        super().resizeEvent(event)


class CheckableListWidget(ListWidget):
    """The whole row toggles once, including clicks on its check indicator."""
    def _checkable(self, item):
        return item is not None and item.flags() & Qt.ItemIsEnabled and item.flags() & Qt.ItemIsUserCheckable

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.LeftButton and self._checkable(item):
            self.setFocus()
            self.setCurrentItem(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.LeftButton and self._checkable(item):
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        item = self.currentItem()
        if event.key() == Qt.Key_Space and self._checkable(item):
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            event.accept()
            return
        super().keyPressEvent(event)


class DragGrip(QToolButton):
    MIME = 'application/x-mad-task'
    dragEnded = pyqtSignal()

    def __init__(self, card, parent):
        super().__init__(parent)
        self.card, self.task_id = card, card.task_id
        self.origin = None
        self.setText('⠿')
        self.setFixedSize(24, 30)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('拖动调整顺序；也可右键或 Alt + ↑ / ↓')

    def mousePressEvent(self, event):
        self.origin = event.pos() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.origin is not None and event.buttons() & Qt.LeftButton and
                (event.pos() - self.origin).manhattanLength() >= QApplication.startDragDistance()):
            self.origin = None  # Escape ends this press even if the mouse is still held.
            mime = QMimeData()
            mime.setData(self.MIME, self.task_id.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            set_drag_badge(drag, self.card.title.text(), self.card.theme)
            try:
                drag.exec_(Qt.MoveAction)
            finally:
                self.setDown(False)
                self.dragEnded.emit()
                drag.deleteLater()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.origin = None
            event.accept()  # Releasing a drag grip is never a click on the expandable header.


class TaskCard(QFrame):
    """One expandable task row, retaining its instance identity and actions."""
    moveRequested = pyqtSignal(str, int)
    dropRequested = pyqtSignal(str, str, bool)
    dropHovered = pyqtSignal(str, str, bool)
    dropLeft = pyqtSignal()

    def __init__(self, task_id, title, theme, parent=None):
        super().__init__(parent)
        self.task_id, self.theme = task_id, theme
        self.busy = False
        self.setProperty('active', False)
        self._highlight = Transition(self, 180)
        self._highlight.valueChanged.connect(lambda _: self.update())
        self.setObjectName('taskCard')
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QFrame(self)
        self.header.setMinimumHeight(76)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        self.grip = DragGrip(self, self.header)
        self.check = CheckBox(self.header)
        self.check.setFixedWidth(26)
        self.check.setObjectName(task_id + '.enabled')
        self.check.setAccessibleName(title + '启用')
        self.title = typography(QLabel(title, self.header), 'body', True)
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.title.setTextFormat(Qt.PlainText)
        self.summary = typography(ElidedLabel(self.header), 'caption')
        self.summary.setTextFormat(Qt.PlainText)
        self.result = typography(QLabel('', self.header), 'caption')
        self.result.setTextFormat(Qt.PlainText)
        self.expand = QToolButton(self.header)
        self.expand.setCheckable(True)
        self.expand.setFixedSize(32, 32)
        self.expand.setToolTip('展开参数')
        self.expand.setAccessibleName(title + '展开参数')
        for widget in (self.grip, self.check): row.addWidget(widget, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(self.title)
        text.addWidget(self.summary)
        row.addLayout(text, 1)
        row.addWidget(self.result)
        row.addWidget(self.expand)
        self.more = QToolButton(self.header)
        self.more.setText('⋯')
        self.more.setToolTip('指令操作')
        self.more.setAccessibleName('指令操作')
        self.more.setFixedSize(32, 32)
        self.more.setPopupMode(QToolButton.InstantPopup)
        row.addWidget(self.more)
        outer.addWidget(self.header)
        self.body = QFrame(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(44, 0, 16, 16)
        self.reveal = Reveal(self.expand, self.body, self)
        outer.addWidget(self.reveal)
        self.expand.toggled.connect(self.set_expanded)
        for widget in (self.header, self.title, self.summary):
            widget.installEventFilter(self)
            widget.setCursor(Qt.PointingHandCursor)
        self.actions_order = []
        for title, delta, shortcut in [('上移', -1, 'Alt+Up'), ('下移', 1, 'Alt+Down')]:
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda _, d=delta: self.moveRequested.emit(self.task_id, d))
            self.addAction(action)
            self.actions_order.append(action)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.menu = QMenu(self)
        self.menu.addActions(self.actions_order)
        self.more.setMenu(self.menu)
        self.customContextMenuRequested.connect(self._menu)
        theme.changed.connect(self.apply_theme)
        self.apply_theme()

    def _menu(self, point):
        if not self.busy: self.menu.exec_(self.mapToGlobal(point))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.expand.toggle()
            event.accept()
            return True  # A label's release must not toggle again on its parent header.
        return super().eventFilter(obj, event)

    def set_expanded(self, expanded):
        if self.expand.isChecked() != expanded:
            self.expand.setChecked(expanded)  # toggled also covers mouse and keyboard
            return
        action = '收起参数' if expanded else '展开参数'
        self.expand.setAccessibleName(self.title.text() + action)
        self.expand.setToolTip(action)
        self.reveal.set_open(expanded)

    def keyPressEvent(self, event):
        if self.hasFocus() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.expand.toggle()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_busy(self, busy, supported=True):
        self.busy = busy
        self.check.setEnabled(not busy and supported)
        self.grip.setEnabled(not busy)
        self.more.setEnabled(not busy)
        self.body.setEnabled(not busy)
        for action in self.actions_order: action.setEnabled(not busy)

    def _drop_slot(self, event):
        grip = event.source()
        if (not self.busy and isinstance(grip, DragGrip) and self.rect().contains(event.pos())
                and grip.card.parentWidget() is self.parentWidget() and event.mimeData().hasFormat(DragGrip.MIME)):
            return grip.task_id, self.task_id, event.pos().y() < self.height() / 2

    def dragMoveEvent(self, event):
        slot = self._drop_slot(event)
        if slot:
            self.dropHovered.emit(*slot)
            event.acceptProposedAction()
        else:
            self.dropLeft.emit()
            event.ignore()

    def dragEnterEvent(self, event):
        self.dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.dropLeft.emit()
        event.accept()

    def dropEvent(self, event):
        self.dropLeft.emit()
        slot = self._drop_slot(event)
        if slot:
            self.dropRequested.emit(*slot)
            event.acceptProposedAction()
        else:
            event.ignore()

    def set_result(self, text='', reason='', active=False):
        if (text, reason, active) == (self.result.text(), self.result.toolTip(), self.property('active')):
            return
        self.result.setText(text)
        self.result.setToolTip(reason)
        self.setProperty('active', active)
        self._style_result()
        self._highlight.move_to(active)

    def paintEvent(self, event):
        super().paintEvent(event)
        value = self._highlight.currentValue()
        if value:
            s = self.theme.surfaces
            p = QPainter(self)
            p.setOpacity(value)
            p.fillRect(3, 0, self.width()-3, self.height()-1, QColor(s['selected']))
            if not self.hasFocus():
                p.fillRect(0, 0, 3, self.height()-1, QColor(s['accent']))

    def apply_theme(self):
        s, c = self.theme.surfaces, self.theme.colors
        self.setStyleSheet(f'QFrame#taskCard {{background:{s["card"]}; border:0; border-left:3px solid transparent;border-bottom:1px solid {s["line"]};}} '
                           f'QFrame#taskCard:focus {{border-left-color:{s["focus"]};}} '
                           f'QToolButton {{border:0; background:transparent; color:{s["muted"]}; border-radius:4px;}} '
                           f'QToolButton:hover {{background:{s["selected"]};}} QToolButton:focus {{border:1px solid {s["focus"]};}} '
                           f'QToolButton::menu-indicator {{image:none;}}')
        self.title.setStyleSheet(f'color:{c["text"]};')
        self.summary.setStyleSheet(f'color:{s["muted"]};')
        self._style_result()

    def _style_result(self):
        s, c = self.theme.surfaces, self.theme.colors
        color = s['accent'] if self.property('active') else (
            c['text__error'] if self.result.text() in ('未完成', '失败', '需处理') else
            c['text__warning'] if self.result.text().startswith(('有余项', '待续')) else s['muted'])
        self.result.setStyleSheet(f'color:{color};')

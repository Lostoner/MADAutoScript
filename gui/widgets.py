"""Small BAAS widgets extracted without the game-specific UI import graph.

Source: pur1fying/blue_archive_auto_script@1110e88df5955df277737ea9717869b9ca88362b
gui/util/customized_ui.py, GPL-3.0-only. The three class implementations
below are retained unchanged, with only their import context extracted.
"""
from typing import Union

from PyQt5.QtCore import QEvent, Qt, pyqtSignal, QMimeData
from PyQt5.QtGui import QIcon, QDrag
from PyQt5.QtWidgets import QLabel, QFrame, QHBoxLayout, QVBoxLayout, QToolButton, QMenu, QAction, QApplication, QSizePolicy, QListWidget
from qfluentwidgets import ExpandSettingCard, FluentIcon as FIF, LineEdit, CheckBox
from gui.theme import typography


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


class CheckableListWidget(QListWidget):
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

    def __init__(self, task_id, parent):
        super().__init__(parent)
        self.task_id = task_id
        self.setText('⠿')
        self.setFixedSize(24, 30)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('拖动调整顺序；也可右键或 Alt + ↑ / ↓')

    def mousePressEvent(self, event):
        self.origin = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and (event.pos() - self.origin).manhattanLength() >= QApplication.startDragDistance():
            mime = QMimeData()
            mime.setData(self.MIME, self.task_id.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec_(Qt.MoveAction)
        else:
            super().mouseMoveEvent(event)


class TaskCard(QFrame):
    """One card for every task; only its parameter widget varies."""
    moveRequested = pyqtSignal(str, int)
    dropRequested = pyqtSignal(str, str, bool)

    def __init__(self, task_id, title, theme, parent=None):
        super().__init__(parent)
        self.task_id, self.theme = task_id, theme
        self.busy = False
        self.setObjectName('taskCard')
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QFrame(self)
        self.header.setFixedHeight(56)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 0, 12, 0)
        row.setSpacing(10)
        self.grip = DragGrip(task_id, self.header)
        self.check = CheckBox(self.header)
        self.check.setFixedWidth(26)
        self.check.setObjectName(task_id + '.enabled')
        self.check.setAccessibleName(title + '启用')
        self.title = typography(QLabel(title, self.header), 14, True)
        self.summary = typography(ElidedLabel(self.header), 13)
        self.result = typography(QLabel('', self.header), 12)
        self.expand = QToolButton(self.header)
        self.expand.setText('⌄')
        self.expand.setCheckable(True)
        self.expand.setFixedSize(26, 30)
        self.expand.setToolTip('展开参数')
        for widget in (self.grip, self.check, self.title): row.addWidget(widget)
        row.addWidget(self.summary, 1)
        row.addWidget(self.result)
        row.addWidget(self.expand)
        outer.addWidget(self.header)
        self.body = QFrame(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(44, 0, 14, 14)
        self.body.setVisible(False)
        outer.addWidget(self.body)
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
        self.customContextMenuRequested.connect(self._menu)
        theme.changed.connect(self.apply_theme)
        self.apply_theme()

    def _menu(self, point):
        menu = QMenu(self)
        menu.addActions(self.actions_order)
        menu.exec_(self.mapToGlobal(point))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.expand.toggle()
        return super().eventFilter(obj, event)

    def set_expanded(self, expanded):
        self.expand.setChecked(expanded)
        self.expand.setText('⌃' if expanded else '⌄')
        self.body.setVisible(expanded)

    def set_busy(self, busy, supported=True):
        self.busy = busy
        self.check.setEnabled(not busy and supported)
        self.grip.setEnabled(not busy)
        self.body.setEnabled(not busy)
        for action in self.actions_order: action.setEnabled(not busy)

    def dragEnterEvent(self, event):
        if not self.busy and event.mimeData().hasFormat(DragGrip.MIME): event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.busy and event.mimeData().hasFormat(DragGrip.MIME):
            source = bytes(event.mimeData().data(DragGrip.MIME)).decode()
            self.dropRequested.emit(source, self.task_id, event.pos().y() < self.height() / 2)
            event.acceptProposedAction()

    def set_result(self, text='', reason='', active=False):
        self.result.setText(text)
        self.result.setToolTip(reason)
        self.setProperty('active', active)
        self.apply_theme()

    def apply_theme(self):
        s, c = self.theme.surfaces, self.theme.colors
        border = s['accent'] if self.property('active') else s['line']
        bg = s['selected'] if self.property('active') else s['card']
        self.setStyleSheet(f'QFrame#taskCard {{background:{bg}; border:1px solid {border}; border-radius:9px;}} '
                           f'QToolButton {{border:0; background:transparent; color:{s["muted"]}; border-radius:4px;}} '
                           f'QToolButton:hover {{background:{s["selected"]};}}')
        self.title.setStyleSheet(f'color:{c["text"]};')
        self.summary.setStyleSheet(f'color:{s["muted"]};')
        self.result.setStyleSheet(f'color:{s["accent"] if self.property("active") else s["muted"]};')

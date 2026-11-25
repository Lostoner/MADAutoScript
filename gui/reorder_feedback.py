"""Native drag preview, insertion line and a short landing for the changed rows only."""
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt, QEasingCurve
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QFrame, QWidget

from gui import motion


def set_drag_badge(drag, text, theme, icon=None):
    source = drag.source()
    metrics = source.fontMetrics()
    text = metrics.elidedText(text, Qt.ElideRight, 192)
    left = 36 if icon else 12
    width, height = left + metrics.horizontalAdvance(text) + 12, max(32, metrics.height() + 8)
    scale = source.devicePixelRatioF()
    image = QPixmap(round(width * scale), round(height * scale))
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(theme.surfaces['accent']))
    p.setBrush(QColor(theme.surfaces['card']))
    p.drawRoundedRect(1, 1, width-2, height-2, 6, 6)
    if icon:
        icon.paint(p, QRect(6, (height-24)//2, 24, 24))
    p.setFont(source.font())
    p.setPen(QColor(theme.colors['text']))
    p.drawText(QRect(left, 0, width-left, height), Qt.AlignLeft | Qt.AlignVCenter, text)
    p.end()
    drag.setPixmap(image)
    drag.setHotSpot(QPoint(6, 2))


class ReorderFeedback(QWidget):
    """The model and all hit targets are already in their final positions while landing."""
    def __init__(self, area, theme, surface):
        viewport = area.viewport()
        super().__init__(viewport)
        self.theme, self.surface = theme, surface
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self.line = QFrame(viewport)
        self.line.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.line.hide()
        self._style_line()
        theme.changed.connect(self._style_line)
        self.motion = motion.Transition(viewport, 180)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.rows = []
        self.image = QPixmap()
        self.motion.valueChanged.connect(self._frame)
        self.motion.move_to(True, animate=False)
        for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            bar.valueChanged.connect(self.clear)

    def _style_line(self):
        self.line.setStyleSheet(f'background:{self.theme.surfaces["accent"]};border:0;border-radius:1px;')

    def mark(self, rect, before):
        if self.rows:
            self.clear()
        rect = rect.intersected(self.parentWidget().rect())
        if rect.width() <= 12 or rect.height() < 3:
            self.line.hide()
            return
        self.line.setGeometry(rect.left()+6, rect.top() if before else rect.bottom()-2,
                              rect.width()-12, 3)
        self.line.raise_()
        self.line.show()

    def clear(self):
        self.line.hide()
        if self.rows:
            self.motion.move_to(True, animate=False)

    def land(self, source, target, row_rect):
        self.clear()
        host = self.parentWidget()
        if source == target or not motion.motion_allowed(host):
            return
        # The dragged badge is already at the drop. It settles last over its neighbours;
        # even an expanded task never travels the entire length of the list a second time.
        direction = 1 if target > source else -1
        bounds, rows = QRect(), []
        for i in range(source, target+direction, direction):
            rect = row_rect(i).intersected(host.rect())
            if not rect.isEmpty():
                bounds = bounds.united(rect)
                distance = min(8, rect.height()//9) if i == target else min(14, rect.height()//6)
                rows.append((rect, (-direction if i == target else direction) * distance))
        if not rows:
            return
        self.image = host.grab(bounds)
        self.rows = [(r.translated(-bounds.topLeft()), dy) for r, dy in rows]
        self.setGeometry(bounds)
        self.motion.move_to(False, animate=False)
        self.raise_()
        self.show()
        QApplication.instance().installEventFilter(self)
        self.motion.move_to(True)

    def _frame(self, value):
        if value == 1:
            QApplication.instance().removeEventFilter(self)
            self.hide()
            self.rows = []
            self.image = QPixmap()
        else:
            self.update()

    def eventFilter(self, obj, event):
        # Resume live painting before the next click, shortcut or scroll is delivered.
        if event.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel) or (
                obj is self.parentWidget() and event.type() == QEvent.Resize):
            self.clear()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.theme.surfaces[self.surface]))
        remaining = 1 - self.motion.currentValue()
        for rect, offset in self.rows:
            dy = round(offset * remaining)
            p.setClipRect(rect.intersected(rect.translated(0, dy)))
            p.drawPixmap(0, dy, self.image)

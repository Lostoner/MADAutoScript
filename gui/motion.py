"""Short, reversible Qt presentation transitions. None of these commit application state."""
import sys

from PyQt5.QtCore import QEvent, QEasingCurve, QPointF, Qt, QVariantAnimation
from PyQt5.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLayout, QStyle, QToolButton,
                             QVBoxLayout, QWidget, QWIDGETSIZE_MAX)


def motion_allowed(widget):
    if (not widget.isVisible() or not widget.isActiveWindow()
            or widget.window().isMinimized() or QApplication.applicationState() != Qt.ApplicationActive):
        return False
    # visibleRegion() subtracts opaque children: a fully visible editor can leave its
    # stack/viewport with no pixels of its own. Clip to ancestors, including the scrollport.
    part, ancestor = widget.rect(), widget
    while not ancestor.isWindow() and not part.isEmpty():
        part.translate(ancestor.pos())
        ancestor = ancestor.parentWidget()
        part = part.intersected(ancestor.rect())
    return not part.isEmpty() and _system_animates(widget)


def _system_animates(widget):
    if sys.platform == 'win32':
        import ctypes
        enabled = ctypes.c_int()
        # Windows Accessibility > Visual effects > Animation effects (read only).
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    return bool(widget.style().styleHint(QStyle.SH_Widget_Animate, None, widget))


class Transition(QVariantAnimation):
    """A single 0..1 timeline. Reversing preserves its current frame, not a queued callback."""
    def __init__(self, widget, duration):
        super().__init__(widget)
        self.target = False
        self.setDuration(duration)
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.setEasingCurve(QEasingCurve.InOutSine)
        widget.installEventFilter(self)
        QApplication.instance().applicationStateChanged.connect(self._app_state)

    def move_to(self, on, animate=True):
        if on == self.target and animate:
            return
        self.target = on
        end = self.duration() if on else 0
        if not animate or self.currentTime() == end or not motion_allowed(self.parent()):
            self.settle()
            return
        self.setDirection(self.Forward if on else self.Backward)
        if self.state() != self.Running:
            self.start()

    def settle(self):
        self.stop()
        self.setCurrentTime(self.duration() if self.target else 0)

    def _app_state(self, state):
        if state != Qt.ApplicationActive and self.state() == self.Running:
            self.settle()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Hide, QEvent.WindowDeactivate) and self.state() == self.Running:
            self.settle()
        return False


class ContentFade(QWidget):
    """Reveal the live destination, never an image or input target from the previous day."""
    def __init__(self, content, theme):
        super().__init__(content)
        self.theme = theme
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self.motion = Transition(content, 180)
        self.motion.valueChanged.connect(self._frame)
        self.motion.move_to(True, animate=False)
        content.installEventFilter(self)

    def reveal(self):
        host = self.parentWidget()
        if not motion_allowed(host):
            self.motion.move_to(True, animate=False)
            return
        if self.motion.state() != self.motion.Running:
            self.motion.move_to(False, animate=False)
        self.setGeometry(host.rect())
        self.show()
        self.raise_()
        self.motion.move_to(True)  # Rapid navigation retains the current opacity.

    def _frame(self, value):
        if value == 1: self.hide()
        else: self.update()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, event):
        color = QColor(self.theme.surfaces['page'])
        color.setAlphaF(.32 * (1-self.motion.currentValue()))
        QPainter(self).fillRect(self.rect(), color)


class _Chevron(QWidget):
    """Only the ink rotates; the native button owns input, text, focus and accessible state."""
    def __init__(self, button):
        super().__init__(button)
        self.progress = 0.0
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(button)
        icon_only = isinstance(button, QToolButton)
        layout.setContentsMargins(0, 0, 0 if icon_only else 12, 0)
        layout.addWidget(self, 0, Qt.AlignCenter if icon_only else Qt.AlignRight | Qt.AlignVCenter)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.rect().center() + QPointF(.5, .5))
        p.rotate(180 * self.progress)
        p.setPen(QPen(self.parentWidget().palette().color(QPalette.ButtonText), 1.6,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(-4, -2), QPointF(0, 2), QPointF(4, -2)]))


class Reveal(QWidget):
    """Clip a full-sized native form, then give sizing back to its layout when open."""
    def __init__(self, button, content, parent):
        super().__init__(parent)
        self.button, self.content = button, content
        if button.text():
            button.setAccessibleName('展开' + button.text())
        self.arrow = _Chevron(button)
        self.motion = Transition(button, 200)
        self.motion.valueChanged.connect(self._present)
        self.extent = 0
        self._min_height = content.minimumHeight()
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        content.hide()
        self.hide()

    def set_open(self, opened, *, animate=True, extent=None):
        if opened == self.motion.target and animate:
            return
        if self.button.text():
            self.button.setAccessibleName(('收起' if opened else '展开') + self.button.text())
        if not opened and self.content.isAncestorOf(QApplication.focusWidget()):
            self.button.setFocus(Qt.OtherFocusReason)
        if opened:
            self.content.show()
            self.show()
        if self.motion.state() != self.motion.Running:
            width = self.parentWidget().contentsRect().width()
            hint = self.content.heightForWidth(width)
            self.extent = extent if extent is not None else (
                max(self.content.minimumSizeHint().height(), hint if hint >= 0 else self.content.sizeHint().height())
                if opened else self.height())
        self.setEnabled(opened)
        self.motion.move_to(opened, animate)
        self._present(self.motion.currentValue())

    def _present(self, value):
        self.arrow.progress = value
        self.arrow.update()
        if value == float(self.motion.target):
            if not self.motion.target:
                self.hide()
                self.content.hide()
            self.content.setMinimumHeight(self._min_height)
            self.setMinimumHeight(0)
            self.setMaximumHeight(QWIDGETSIZE_MAX)
            self.setEnabled(True)
        else:
            self.content.setMinimumHeight(self.extent)
            self.setFixedHeight(round(value * self.extent))

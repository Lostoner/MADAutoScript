"""Exercise the real Qt widgets and drop events; only the platform drag loop is replaced."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from main import create_window


def deliver(drag, receiver, kind, pos):
    class LocalEvent(kind):
        def source(self): return drag.source()
    event = LocalEvent(QPointF(pos) if kind is QDropEvent else pos, Qt.MoveAction,
                       drag.mimeData(), Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(receiver, event)
    return event.isAccepted()


class ReorderMotion(TestCase):
    windows = []

    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.app, self.w = create_window(Path(tmp.name))
        type(self).app = self.app; self.windows.append(self.w)
        self.w._plan_timer.stop(); self.w._preview_timer.stop()
        self.w._fit_initial_size(QRect(0,0,1920,1080))
        self.w.show(); self.app.processEvents()
        self.addCleanup(self.w.close)

    def drag(self, widget, pos, platform):
        calls, errors = [], []
        def execute(native, action):
            calls.append(action)
            try:
                self.assertFalse(native.pixmap().isNull())
                return platform(native)
            except Exception as error:
                errors.append(error)
                return Qt.IgnoreAction
        with patch.object(QDrag, 'exec_', new=execute):
            QTest.mousePress(widget, Qt.LeftButton, pos=pos)
            for dx in (3, QApplication.startDragDistance()+5):
                point = pos+QPoint(dx,0)
                QApplication.sendEvent(widget, QMouseEvent(QEvent.MouseMove, QPointF(point),
                    QPointF(widget.mapToGlobal(point)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            QTest.mouseRelease(widget, Qt.LeftButton, pos=pos)
        if errors: raise errors[0]
        self.assertEqual(calls, [Qt.MoveAction])

    @patch('gui.motion._system_animates', return_value=True)
    def test_task_hover_cancel_and_drop_only_move_the_indicated_instances(self, _):
        page = self.w.routineInterface
        order = lambda: [e['instance_id'] for e in page._queue]
        before = order()
        grip, target = page.cards[before[0]].grip, page.cards[before[2]]
        cue = page.reorder_feedback
        top, bottom = QPoint(18,2), QPoint(18,target.height()-2)
        def hover(native):
            self.assertTrue(deliver(native, target, QDragEnterEvent, top))
            self.assertEqual(cue.line.y(), page._card_rect(target.task_id).top())
            deliver(native, target, QDragMoveEvent, bottom)
            self.assertEqual(cue.line.geometry().bottom(), page._card_rect(target.task_id).bottom())
            self.assertEqual(order(), before)
            self.assertFalse(page.has_unsaved_changes())
        def cancel(native):
            hover(native)
            QApplication.sendEvent(target,QDragLeaveEvent())
            self.assertTrue(cue.line.isHidden())
            hover(native)
            return Qt.IgnoreAction  # Escape/ignored release, even without a final leave event
        self.drag(grip, grip.rect().center(), cancel)
        self.assertTrue(cue.isHidden() and cue.line.isHidden())
        self.assertFalse(grip.card.expand.isChecked())
        self.assertEqual(order(), before)
        self.assertFalse(page.has_unsaved_changes())
        def drop(native):
            hover(native)
            self.assertTrue(deliver(native, target, QDropEvent, bottom))
            return Qt.MoveAction
        self.drag(grip, grip.rect().center(), drop)
        self.assertFalse(grip.card.expand.isChecked())
        self.assertEqual(order(), [*before[1:3],before[0],*before[3:]])
        self.assertTrue(cue.line.isHidden() and cue.isVisible())
        self.assertEqual(len(cue.rows), 3)
        self.assertLess(cue.geometry().bottom(), page._card_rect(before[3]).top())
        # Keyboard input supersedes the visual landing, without losing the new order.
        card=page.cards[before[0]]; card.setFocus()
        QTest.keyClick(card,Qt.Key_Up,Qt.AltModifier)
        self.assertTrue(cue.isHidden())
        self.assertEqual(order()[:3],[before[1],before[0],before[2]])
        page.cancel_changes()
        self.assertEqual(order(), before)

    @patch('gui.motion._system_animates', return_value=True)
    def test_material_drop_preserves_controls_and_cancel_never_changes_the_draft(self, _):
        from gui.fragments.materials import MaterialDialog
        dialog=MaterialDialog(self.w.repository,self.w.theme,'mad.material_sweep',parent=self.w)
        self.addCleanup(dialog.hide)
        refs=['item:80201','item:80204','goods:1','item:29']
        dialog.add_targets(refs)
        dialog.table.cellWidget(2,5).setChecked(True); dialog.amount_box(2).setValue(75)
        before=dialog.values(); amount=dialog.amount_box(2)
        dialog.show(); self.app.processEvents()
        table=dialog.table; cue=table.reorder_feedback
        centers=lambda row: table.visualItemRect(table.item(row,1)).center()
        untouched=table._row_rect(3)
        def cancel(native):
            self.assertTrue(deliver(native,table.viewport(),QDragEnterEvent,centers(0)))
            self.assertTrue(cue.line.isVisible())
            QApplication.sendEvent(table.viewport(),QDragLeaveEvent())
            return Qt.IgnoreAction
        self.drag(table.viewport(),centers(2),cancel)
        self.assertEqual(dialog.values(),before)
        self.assertTrue(cue.line.isHidden() and cue.isHidden())
        def drop(native):
            deliver(native,table.viewport(),QDragEnterEvent,centers(1))
            deliver(native,table.viewport(),QDragMoveEvent,centers(0))
            self.assertEqual(cue.line.y(),table._row_rect(0).top())
            self.assertTrue(deliver(native,table.viewport(),QDropEvent,centers(0)))
            return Qt.MoveAction
        self.drag(table.viewport(),centers(2),drop)
        self.assertEqual(dialog.values(),[before[2],before[0],before[1],before[3]])
        self.assertEqual(table.currentRow(),0)
        self.assertIs(dialog.amount_box(0),amount)
        self.assertEqual(table._row_rect(3),untouched)
        self.assertEqual([dialog.rule_target.itemData(i) for i in range(4)],[refs[2],refs[0],refs[1],refs[3]])
        self.assertEqual(len(cue.rows),3)
        self.assertTrue(cue.line.isHidden())
        QTest.qWait(260)
        self.assertTrue(cue.isHidden())
        # With Windows animations off the insertion line still marks an append to the end.
        def append(native):
            pos=QPoint(centers(3).x(),table._row_rect(3).bottom()+4)
            self.assertTrue(deliver(native,table.viewport(),QDragEnterEvent,pos))
            self.assertEqual(cue.line.geometry().bottom(),table._row_rect(3).bottom())
            self.assertTrue(cue.line.isVisible())
            self.assertTrue(deliver(native,table.viewport(),QDropEvent,pos))
            return Qt.MoveAction
        with patch('gui.motion._system_animates',return_value=False):
            self.drag(table.viewport(),centers(0),append)
        self.assertEqual(dialog.values(),[before[0],before[1],before[3],before[2]])
        self.assertTrue(cue.isHidden() and cue.line.isHidden())
        self.assertEqual(dialog.store.definitions()['targets'],[])

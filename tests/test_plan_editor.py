"""Exercise calendar editing through Qt with real isolated plan/profile storage."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from core.config.repository import ProfileRepository
from core.plan_store import PlanStore


class PlanEditorTests(TestCase):
    def setUp(self):
        from gui.qt_bootstrap import configure_qt
        configure_qt()
        from PyQt5.QtWidgets import QApplication
        from gui.theme import ThemeManager
        from gui.fragments.plan import PlanFragment
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app=QApplication.instance() or QApplication(['MAD plan tests'])
        type(self).qt_app=self.app
        self.repo=ProfileRepository(Path(self.tmp.name)/'config/default')
        clock=datetime(2026,11,4,9,tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        self.store=PlanStore(self.repo,clock=lambda:clock)
        self.theme=ThemeManager('dark')
        self.page=PlanFragment(self.store,self.theme)
        self.page.resize(1050,715); self.page.show(); self.app.processEvents()
        self.addCleanup(self.page.close)

    def test_copy_multiple_days_and_save_before_freeze(self):
        from PyQt5.QtCore import Qt,QTimer
        from PyQt5.QtWidgets import QApplication,QDialogButtonBox,QListWidget
        from PyQt5.QtTest import QTest
        p=self.page
        ordinary=self.repo.load_config()
        QTest.mouseClick(p.from_daily,Qt.LeftButton)
        p.editor.cards['mad.normal_sweep'].check.setChecked(True)
        key=p.editor.add_instance('mad.normal_sweep','mad.normal_sweep')
        p.editor.rename_instance(key,'领完清体力')
        stage=p.editor.sweep_selectors[key].value()[0]['stage_id']
        p.editor.sweep_selectors[key].rows[stage][2].setValue(0)
        self.assertEqual(p.draft['days'][p.day]['routine']['params_by_id'][key]['plans'][0]['count'],'max')
        def choose():
            dialog=QApplication.activeModalWidget(); listbox=dialog.findChild(QListWidget)
            for i in range(listbox.count()):
                item=listbox.item(i)
                item.setCheckState(Qt.Checked if i<2 else Qt.Unchecked)
            dialog.accept()
        QTimer.singleShot(0,choose); p._copy_dialog()
        self.assertEqual(len(p.draft['days']),3)
        p.days.setCurrentRow(1)
        p.editor.sweep_selectors[key].rows[stage][2].setValue(3)
        self.assertTrue(p.has_unsaved_changes())
        self.assertFalse(p.start.isEnabled())
        self.assertFalse(self.store.path.exists())
        def confirm_save():
            box=QApplication.activeModalWidget().findChild(QDialogButtonBox)
            QTest.mouseClick(box.button(QDialogButtonBox.Ok),Qt.LeftButton)
        QTimer.singleShot(0,confirm_save); QTest.mouseClick(p.save_button,Qt.LeftButton)
        self.assertFalse(p.has_unsaved_changes(),p.feedback.text())
        plan=self.store.load()
        self.assertEqual([v['routine']['params_by_id'][key]['plans'][0]['count'] for v in plan['days'].values()],['max',3,'max'])
        self.assertEqual(self.repo.load_config(),ordinary)
        self.store.day_repository('2026-11-04')
        p.refresh(); p.days.setCurrentRow(0)
        self.assertTrue(p.editor.cards[key].busy)
        p.days.setCurrentRow(1)
        self.assertFalse(p.editor.cards[key].busy)
        p._mark('rest'); p.cancel_changes()
        self.assertEqual(p.draft['days'][p.day]['kind'],'tasks')

    def test_week_copy_keeps_rest_and_target_preview_defaults(self):
        from PyQt5.QtCore import Qt,QTimer
        from PyQt5.QtWidgets import QApplication,QListWidget
        p=self.page; p.use_daily()
        p.days.setCurrentRow(1); p._mark('rest')
        p.draft['end']='2026-11-17'; p.draft['days']['2026-11-11']={'kind':'rest'}
        p._render()
        def choose_empty():
            dialog=QApplication.activeModalWidget(); box=dialog.findChild(QListWidget)
            assert box.item(0).checkState()==Qt.Unchecked
            assert box.item(1).checkState()==Qt.Checked
            dialog.accept()
        QTimer.singleShot(0,choose_empty);p._copy_week()
        self.assertEqual(p.draft['days']['2026-11-11']['kind'],'rest')
        self.assertEqual(p.draft['days']['2026-11-12']['kind'],'rest')
        self.assertTrue(p.horizon.isVisible())
        self.assertTrue(p.save_changes(),p.feedback.text())
        self.assertEqual(self.store.load()['end'],'2026-11-17')

    def test_history_without_a_status_and_frozen_remaining_preview(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication,QTabWidget,QTextEdit
        p=self.page; key=p.day
        captured=[]
        def read_history():
            dialog=QApplication.activeModalWidget()
            captured.append([w.toPlainText() for w in dialog.findChildren(QTextEdit)])
            dialog.accept()
        self.store.update_record(key,auto_skip=True)
        QTimer.singleShot(0,read_history);p._history(key)
        self.assertIn('尚无已结算步骤',captured[0][0])
        p.use_daily(); self.assertTrue(p.save_changes());self.store.day_repository(key)
        normal='mad.normal_sweep';claim='mad.claim_all'
        self.store.update_record(key,status='partial',remaining=[normal,claim],deferred=[claim],
                                 tasks=[{'task_id':normal,'instance_id':normal,'status':'PARTIAL',
                                         'remaining':[{'stage_id':'normal:5-1','count':3}]}])
        QTimer.singleShot(0,read_history); p._history(key)
        texts='\n'.join(captured[-1])
        for expected in ('剩余 3 次','5-1','禁用时段','一键领取','启用'):
            self.assertIn(expected,texts)
        accepted=[];p.resumeRemainingRequested.connect(lambda:accepted.append(True))
        QTimer.singleShot(0,read_history); p._resume_remaining()
        self.assertEqual(accepted,[True]); self.assertIn('剩余 3 次',captured[-1][0])

    def test_save_preview_warns_only_when_due_and_auto_and_history_does_not_lock_timezone(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication,QFormLayout
        p=self.page;p.use_daily()
        self.assertNotIn('立即启动',p._preview())
        self.store.set_auto(True);p.refresh()
        self.assertIn('保存后可能立即启动',p._preview())
        p.draft['days'][p.day]['time']='17:00'
        self.assertNotIn('立即启动',p._preview())
        self.store.set_auto(False);p.refresh();self.assertTrue(p.save_changes())
        self.store.day_repository(p.day)
        flags=[]
        def inspect():
            d=QApplication.activeModalWidget()
            flags.append(d.layout().itemAt(3,QFormLayout.FieldRole).widget().isEnabled());d.reject()
        QTimer.singleShot(0,inspect);p._settings()
        self.store.clock=lambda:datetime(2026,11,5,9,tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        QTimer.singleShot(0,inspect);p._settings()
        self.assertEqual(flags,[False,True])

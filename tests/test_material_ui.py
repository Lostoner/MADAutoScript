"""Native material editor acceptance with isolated profiles, never ADB."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from core.material_store import MaterialStore, TASK
from core.plan_store import PlanStore
from gui.fragments.materials import MaterialDialog
from gui.material_picker import MaterialPicker, material_icon

A='item:80201'


class MaterialUI(TestCase):
    # Fluent TitleLabel keeps app-wide theme callbacks. Match the QApplication
    # lifetime for closed test windows; only dispose the new material dialog.
    windows=[]

    def setUp(self):
        from main import create_window
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.app,self.window=create_window(Path(tmp.name)); type(self).app=self.app
        type(self).windows.append(self.window)
        self.repo=self.window.repository
        self.dialog=MaterialDialog(self.repo,self.window.theme,TASK,parent=self.window)
        self.addCleanup(self.close)

    def close(self):
        from PyQt5.QtCore import QCoreApplication,QEvent
        self.dialog.targets=self.dialog.store.definitions()['targets']
        self.dialog.base=self.dialog.store.definitions(); self.dialog.render_targets()
        self.dialog.close(); self.dialog.deleteLater()
        self.window.close()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete); self.app.processEvents()

    def test_save_applies_shared_targets_without_starting_and_unknown_is_visible(self):
        before=self.repo.load_config()['unfinished_tasks']
        self.dialog.add_target(A,50); self.dialog.show(); self.app.processEvents()
        self.assertEqual(self.dialog.table.item(0,2).text(),'待同步')
        self.assertTrue(self.dialog.save_targets())
        self.assertIsNone(self.window.worker)
        self.assertEqual(self.repo.load_config()['unfinished_tasks'],before)
        self.assertEqual(MaterialStore(self.repo).definitions()['targets'][0]['amount'],50)
        self.assertEqual(self.dialog.preview.rowCount(),0)
        self.assertIn('库存待同步',self.dialog.waiting.text())
        self.dialog.table.cellWidget(0,0).setChecked(False); self.dialog.save_targets()
        self.assertEqual(self.dialog.table.item(0,6).text(),'已暂停')
        self.dialog.store.freeze('paused')
        page=self.window.routineInterface
        page.on_event({'kind':'result','state':'succeeded','result':{'tasks':[
            {'task_id':TASK,'instance_id':TASK,'status':'SKIPPED','material_context':'paused'}]}})
        self.assertEqual(page.cards[TASK].result.text(),'已跳过')

    def test_adjustment_is_not_copied_as_instruction_parameter_and_busy_is_read_only(self):
        self.dialog.add_target(A,50); self.dialog.save_targets()
        self.dialog.rule_cap.setValue(2); self.dialog.save_rule()
        self.assertEqual(self.dialog.store.adjustments('routine',TASK)[A]['max_runs'],2)
        page=self.window.routineInterface
        copy=page.add_instance(TASK)
        self.assertEqual(page.editors[copy].value(),{'reserve':0})
        self.assertTrue(page.save_changes())
        self.assertEqual(self.dialog.store.adjustments('routine',copy),{})
        self.dialog.set_busy(True)
        self.assertFalse(self.dialog.sync_button.isEnabled());self.assertFalse(self.dialog.apply_rule.isEnabled())

    def test_pending_is_visible_and_future_view_does_not_allocate_today_stamina(self):
        self.dialog.add_target(A,50); self.dialog.save_targets()
        store=self.dialog.store; snap=store.freeze('round')
        store.prepare_batch('round',TASK,'normal:4-1',1,[A])
        self.dialog.refreshed();self.assertFalse(self.dialog.review.isHidden())
        store.resolve_pending(False)
        store.observe({'inventory':{A:0},'balance':100,'stages':{'normal:4-1':{'status':'sweepable'}},'source':'game','at':1},snap)
        self.dialog.scope='plan:2099-01-01';self.dialog.refresh_preview()
        self.assertEqual(self.dialog.preview.rowCount(),0)
        self.assertIn('未来日期',self.dialog.context.text())

    def test_card_buttons_use_existing_window_integration(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication
        def check_dialog():
            modal=QApplication.activeModalWidget()
            self.assertIsInstance(modal,MaterialDialog)
            self.assertEqual(modal.tabs.currentIndex(),1)
            modal.reject()
        QTimer.singleShot(0,check_dialog)
        self.window.routineInterface.materialRequested.emit(TASK,'plan')
        self.assertIsNone(self.window.worker)

    def test_frozen_card_keeps_table_access_but_not_parameter_edits(self):
        page=self.window.routineInterface; page.set_busy(True)
        editor=page.editors[TASK]
        self.assertTrue(editor.material_buttons['plan'].isEnabled())
        self.assertFalse(editor.material_buttons['sync'].isEnabled())
        self.assertFalse(editor.material_reserve.isEnabled())
        self.assertFalse(page.cards[TASK].check.isEnabled())

    def test_dialog_stop_and_sync_failure_feedback_are_accessible(self):
        self.window.material_dialog=self.dialog
        stopped=Mock(); self.dialog.stopRequested.connect(stopped)
        self.dialog.set_busy(True); self.dialog.stop_button.click()
        stopped.assert_called_once()
        self.window._on_runtime_event({'kind':'result','state':'failed','material_sync':True,
            'result':{'error':'traceback\n库存未读取','tasks':[]}})
        self.assertIn('库存未读取',self.dialog.feedback.text())
        self.assertTrue(self.dialog.sync_button.isEnabled()); self.assertTrue(self.dialog.stop_button.isHidden())
        self.window.material_dialog=None

    def test_frozen_unknown_batch_never_displays_an_executable_table(self):
        self.dialog.add_target(A,50); self.dialog.save_targets()
        scope='plan:'+PlanStore(self.repo).today()
        self.dialog.scope=scope
        store=self.dialog.store; snap=store.freeze(scope,scope)
        store.observe({'inventory':{A:0},'balance':100,'stages':{'normal:4-1':{'status':'sweepable'}},'source':'game','at':1},snap)
        store.prepare_batch(scope,TASK,'normal:4-1',1,[A])
        self.dialog.refresh_preview()
        self.assertEqual(self.dialog.preview.rowCount(),0); self.assertIn('待核对',self.dialog.waiting.text())
        store.resolve_pending(True); self.dialog.refresh_preview()
        self.assertEqual(self.dialog.preview.rowCount(),0); self.assertIn('额度已结束',self.dialog.waiting.text())

    def picker(self,existing=()):
        picker=MaterialPicker(self.dialog.data['items'],existing,self.window.theme,self.dialog)
        picker.resize(920,690); picker.show(); self.app.processEvents()
        self.addCleanup(picker.deleteLater); self.addCleanup(picker.reject)
        return picker

    def test_picker_categories_global_search_and_public_thumbnails(self):
        from collections import Counter
        from core.paths import REPO_ROOT
        from scripts.build_release import material_assets, source_files
        from PyQt5.QtCore import Qt
        items=self.dialog.data['items']; picker=self.picker([A])
        self.assertEqual(Counter(i['category'] for i in items.values()),{'voucher':48,'equipment':12,'currency':1})
        self.assertEqual(len(picker.visible_refs),12)
        self.assertTrue(all(items[r]['tier']==2 for r in picker.visible_refs))
        self.assertFalse(picker.rows[A].flags() & Qt.ItemIsEnabled)
        picker.choose_category('equipment'); self.assertEqual(len(picker.visible_refs),12)
        picker.search.setText(' t3  耳环 '); self.assertEqual(picker.visible_refs,['item:80301'])
        picker.search.setText('项链'); self.assertEqual(len(picker.visible_refs),5)
        self.assertIn('item:90102',picker.visible_refs)  # the game calls it 挂脖风扇
        picker.search.setText('T1'); self.assertEqual(len(picker.visible_refs),12)
        picker.search.setText('不存在的素材'); self.assertTrue(picker.empty.isVisible())
        self.assertFalse(picker.add_button.isEnabled())
        picker.choose_category('currency'); self.assertEqual(picker.visible_refs,['goods:1'])
        files=set(material_assets())
        self.assertEqual(len(files),62)
        self.assertIn('gui/material_picker.py',source_files())
        for ref,item in items.items():
            with self.subTest(ref=ref):
                self.assertIn(item['icon'],files)
                self.assertTrue((REPO_ROOT/item['icon']).is_file())
                self.assertFalse(material_icon(item).pixmap(64,72).isNull())
        self.assertIn('来源待实机补验',picker.rows['item:80501'].toolTip())

    def test_picker_names_fit_and_small_window_can_reach_last_material(self):
        from PyQt5.QtGui import QFontMetrics
        from PyQt5.QtTest import QTest
        from gui.theme import ui_font
        picker=self.picker()
        QTest.qWait(30)
        self.assertEqual(picker.grid.verticalScrollBar().maximum(),0)  # all 12 fit by default
        metrics=QFontMetrics(ui_font(14))
        for item in picker.items.values():
            self.assertLessEqual(metrics.horizontalAdvance(item['name']),174)
        picker.resize(760,540); QTest.qWait(30)
        bar=picker.grid.verticalScrollBar()
        self.assertTrue(bar.isVisible()); self.assertGreater(bar.maximum(),0)
        last=picker.rows[picker.visible_refs[-1]]
        picker.grid.scrollToItem(last); QTest.qWait(30)
        self.assertTrue(picker.grid.viewport().rect().contains(picker.grid.visualItemRect(last)))
        self.assertTrue(picker.rect().contains(picker.add_button.geometry()))

    def test_picker_mouse_keyboard_and_cross_category_selection(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        picker=self.picker()
        def click(ref):
            picker.grid.scrollToItem(picker.rows[ref]); self.app.processEvents()
            QTest.mouseClick(picker.grid.viewport(),Qt.LeftButton,pos=picker.grid.visualItemRect(picker.rows[ref]).center())
        click(A); self.assertEqual(picker.selection,[A])
        picker.choose_tier(3); click('item:80302')
        picker.search.setText('信用点'); click('goods:1')
        self.assertEqual(picker.selection,[A,'item:80302','goods:1'])
        self.assertIn('3',picker.add_button.text())
        picker.choose_category('voucher'); picker.choose_tier(2)
        self.assertTrue(picker.rows[A].isSelected())
        picker.grid.setFocus(); picker.grid.setCurrentItem(picker.rows[A])
        QTest.keyClick(picker.grid,Qt.Key_Space)
        self.assertNotIn(A,picker.selection)
        picker.clear_button.click(); self.assertEqual(picker.selection,[])
        self.assertFalse(picker.add_button.isEnabled())

    def test_picker_batch_add_cancel_and_existing_draft_preservation(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication
        self.dialog.add_target(A,50); self.dialog.table.cellWidget(0,3).setValue(75)
        def choose():
            picker=QApplication.activeModalWidget(); self.assertIsInstance(picker,MaterialPicker)
            picker.choose_tier(3)
            picker.rows['item:80301'].setSelected(True); picker.rows['item:80302'].setSelected(True)
            picker.add_button.click()
        QTimer.singleShot(0,choose); self.dialog.add_dialog()
        self.assertEqual([t['ref'] for t in self.dialog.values()],[A,'item:80301','item:80302'])
        self.assertEqual(self.dialog.values()[0]['amount'],75)
        self.assertEqual(self.dialog.table.currentRow(),1)
        self.assertFalse(self.dialog.table.item(1,1).icon().isNull())
        self.assertFalse(self.dialog.rule_target.itemIcon(1).isNull())
        def cancel():
            picker=QApplication.activeModalWidget()
            self.assertEqual(picker.tier,3)  # keep the browsing context in this editor
            picker.choose_tier(4); picker.rows['item:80401'].setSelected(True); picker.cancel_button.click()
        QTimer.singleShot(0,cancel); self.dialog.add_dialog()
        self.assertEqual(len(self.dialog.values()),3)
        self.assertEqual(self.dialog.store.definitions()['targets'],[])
        self.assertIsNone(self.window.worker)

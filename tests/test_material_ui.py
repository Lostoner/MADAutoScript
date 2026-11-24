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
        self.assertEqual(page.editors[copy].value(),{'reserve':0,'targets':[]})
        self.assertTrue(page.save_changes())
        self.assertEqual(self.dialog.store.adjustments('routine',copy),{})
        self.dialog.set_busy(True)
        self.assertFalse(self.dialog.sync_button.isEnabled());self.assertFalse(self.dialog.apply_rule.isEnabled())

    def test_pending_is_visible_and_future_view_does_not_allocate_today_stamina(self):
        self.dialog.add_target(A,50); self.dialog.save_targets()
        store=self.dialog.store; snap=store.for_step(store.freeze('round'),TASK)
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

    def test_daily_dialog_saves_only_one_card_and_copy_is_independent(self):
        from core.config.repository import ProfileRepository
        page=self.window.routineInterface; page.editors[TASK].material_reserve.setValue(20)
        def edit_front(dialog):
            self.assertIn('素材扫荡',dialog.windowTitle())
            dialog.add_target(A,50)
            dialog.save_button.click()
            self.assertIn('已保存此指令',dialog.feedback.text())
            return 0
        with patch.object(MaterialDialog,'exec_',new=edit_front):
            self.window._show_materials('routine',TASK,'goals')
        self.assertEqual(self.repo.load_config()['routine']['material_sweep']['reserve'],0)
        self.assertTrue(page.has_unsaved_changes())
        first=MaterialStore(self.repo).definitions()['targets'][0]
        copy=page.add_instance(TASK,TASK)
        inherited=page.editors[copy].value()['targets'][0]
        self.assertEqual((inherited['ref'],inherited['amount']),(A,50))
        self.assertNotEqual(inherited['version'],first['version'])
        blank=page.add_instance(TASK)
        self.assertEqual(page.editors[blank].value()['targets'],[])
        def edit_tail(dialog):
            self.assertIn('应用到草稿',dialog.save_button.text())
            dialog.table.selectRow(0); dialog.remove_target(); dialog.add_target('item:29')
            self.assertTrue(dialog.save_targets())
            self.assertIn('保存更改',dialog.feedback.text())
            return 0
        with patch.object(MaterialDialog,'exec_',new=edit_tail):
            self.window._show_materials('routine',copy,'goals')
        self.assertNotIn(copy,self.repo.load_config()['instance_params'])
        self.assertTrue(page.save_changes())
        reopened=MaterialStore(ProfileRepository(self.repo.profile_dir))
        self.assertEqual(reopened.definitions()['targets'],[first])
        self.assertEqual([t['ref'] for t in reopened.definitions(copy)['targets']],['item:29'])
        self.assertEqual(reopened.definitions(blank)['targets'],[])
        def sync_tail(dialog):
            dialog.request_sync()
            return 0
        with patch.object(MaterialDialog,'exec_',new=sync_tail),patch.object(self.window,'_sync_materials') as sync:
            self.window._show_materials('routine',copy,'plan')
        snapshot,=sync.call_args.args
        self.assertEqual([t['ref'] for t in snapshot['targets']],['item:29'])

    def test_plan_dialog_edits_one_day_and_frozen_day_keeps_its_goals(self):
        from PyQt5.QtWidgets import QDialog
        from gui.fragments.plan import shift
        material=MaterialStore(self.repo); material.save_targets([{'ref':A}])
        with patch.object(QDialog,'exec_',return_value=0): self.window._show_plan()
        plan_page=self.window.plan_page; plan_page.use_daily()
        today=plan_page.day; other=shift(today,1)
        before=self.repo.load_config()
        def choose(ref):
            def edit(dialog):
                self.assertEqual(dialog.base['targets'][0]['ref'],A)
                dialog.table.selectRow(0); dialog.remove_target(); dialog.add_target(ref)
                self.assertTrue(dialog.save_targets())
                self.assertIn('保存排期',dialog.feedback.text())
                return 0
            return edit
        plan_page.copy_to(today,[other])
        with patch.object(MaterialDialog,'exec_',new=choose('item:29')):
            self.window._show_materials('plan:'+today,TASK,'goals')
        self.assertFalse(self.window.plan_store.load()['days'])
        self.assertTrue(plan_page.save_changes())
        self.window.plan_store.day_repository(today)
        frozen=material.freeze('plan:'+today)
        plan_page.day=other; plan_page._render()
        with patch.object(MaterialDialog,'exec_',new=choose('item:80202')):
            self.window._show_materials('plan:'+other,TASK,'goals')
        self.assertTrue(plan_page.save_changes())
        days=self.window.plan_store.load()['days']
        self.assertEqual([days[d]['routine']['params_by_id'][TASK]['targets'][0]['ref'] for d in (today,other)],
                         ['item:29','item:80202'])
        self.assertEqual(self.repo.load_config(),before)
        self.assertEqual(material.freeze('plan:'+today),frozen)
        plan_page.day=today; plan_page._render()
        def inspect_frozen(dialog):
            self.assertTrue(dialog.read_only)
            self.assertEqual(dialog.base['targets'][0]['ref'],'item:29')
            self.assertFalse(dialog.save_targets())
            return 0
        with patch.object(MaterialDialog,'exec_',new=inspect_frozen):
            self.window._show_materials('plan:'+today,TASK,'plan')

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
        store=self.dialog.store; snap=store.for_step(store.freeze(scope,scope),TASK)
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
        self.assertEqual(Counter(i['category'] for i in items.values()),{'voucher':48,'equipment':12,'memory':29,'currency':1})
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
        self.assertEqual(len(files),91)
        self.assertIn('gui/material_picker.py',source_files())
        for ref,item in items.items():
            with self.subTest(ref=ref):
                self.assertIn(item['icon'],files)
                self.assertTrue((REPO_ROOT/item['icon']).is_file())
                self.assertFalse(material_icon(item).pixmap(64,72).isNull())
        self.assertIn('来源待实机补验',picker.rows['item:80501'].toolTip())

    def test_memory_picker_and_hard_source_adjustment_keep_existing_goal(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        dialog=self.dialog; dialog.add_target(A,50); self.assertTrue(dialog.save_targets())
        existing=dialog.store.definitions()['targets'][0]
        picker=self.picker([A])
        picker.category_buttons['memory'].click(); self.assertEqual(len(picker.visible_refs),29)
        picker.search.setText('雫'); self.assertEqual(picker.visible_refs,['item:17'])
        picker.search.setText('角色碎片 芙蕾雅'); self.assertEqual(picker.visible_refs,['item:29'])
        row=picker.rows['item:29']
        QTest.mouseClick(picker.grid.viewport(),Qt.LeftButton,pos=picker.grid.visualItemRect(row).center())
        self.assertEqual(picker.selection,['item:29'])
        picker.add_button.click()
        dialog.add_targets(picker.selection); self.assertTrue(dialog.save_targets())
        targets=dialog.store.definitions()['targets']
        self.assertEqual(targets[0],existing)
        self.assertEqual((targets[1]['amount'],targets[1]['stock_limit_enabled']),(None,False))
        obs=dict(balance=200,stages={'hard:1-1':dict(status='sweepable',remaining_attempts=1),
                                    'hard:8-1':dict(status='sweepable',remaining_attempts=3),
                                    'hard:15-2':dict(status='unavailable')})
        dialog.store.observe(obs,{'targets':targets})
        dialog.tabs.setCurrentWidget(dialog.plan_page)
        self.assertEqual([dialog.preview.item(i,0).text() for i in range(dialog.preview.rowCount())],['HARD 1-1','HARD 8-1'])
        self.assertFalse(dialog.preview.item(0,0).icon().isNull())
        self.assertIn('每日最多 3 次',dialog.context.text())
        dialog.rule_target.setCurrentIndex(1)
        source=dialog.rule_stage.findData('hard:8-1')
        self.assertEqual(dialog.rule_stage.itemText(source),'HARD 8-1')
        self.assertIn('<img',dialog.rule_stage.itemData(source,Qt.ToolTipRole))
        dialog.rule_stage.setCurrentIndex(source); dialog.rule_cap.setValue(2); dialog.apply_rule.click()
        self.assertEqual((dialog.preview.rowCount(),dialog.preview.item(0,0).text(),dialog.preview.item(0,3).text()),(1,'HARD 8-1','2'))
        self.assertIsNone(self.window.worker)

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
        self.assertEqual(picker.rows['goods:1'].data(Qt.UserRole+2),3)
        self.assertIn('3',picker.add_button.text())
        picker.choose_category('voucher'); picker.choose_tier(2)
        self.assertTrue(picker.rows[A].isSelected())
        picker.grid.setFocus(); picker.grid.setCurrentItem(picker.rows[A])
        QTest.keyClick(picker.grid,Qt.Key_Space)
        self.assertNotIn(A,picker.selection)
        QTest.keyClick(picker.grid,Qt.Key_Space)
        self.assertEqual(picker.selection,['item:80302','goods:1',A])
        self.assertEqual(picker.rows[A].data(Qt.UserRole+2),3)
        picker.clear_button.click(); self.assertEqual(picker.selection,[])
        self.assertFalse(picker.add_button.isEnabled())

    def test_picker_batch_add_cancel_and_existing_draft_preservation(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication
        self.dialog.add_target(A,50); self.dialog.amount_box(0).setValue(75)
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

    def test_default_quantity_free_order_buttons_keyboard_and_drop_persist(self):
        from PyQt5.QtCore import Qt,QMimeData
        from PyQt5.QtTest import QTest
        refs=['item:80204',A,'goods:1']
        self.dialog.add_targets(refs); self.dialog.show(); self.app.processEvents()
        self.assertTrue(self.dialog.table.isColumnHidden(3))
        self.assertTrue(all(not t['stock_limit_enabled'] and t['amount'] is None for t in self.dialog.values()))
        self.dialog.table.selectRow(1); self.dialog.up.click()
        self.assertEqual([t['ref'] for t in self.dialog.values()],[A,refs[0],refs[2]])
        self.dialog.table.setFocus(); QTest.keyClick(self.dialog.table,Qt.Key_Down,Qt.AltModifier)
        self.assertEqual([t['ref'] for t in self.dialog.values()],refs)
        mime=QMimeData(); mime.setData(self.dialog.table.MIME,b'2')
        drop=Mock(); drop.source.return_value=self.dialog.table; drop.mimeData.return_value=mime
        drop.pos.return_value=self.dialog.table.visualItemRect(self.dialog.table.item(0,1)).center()
        self.dialog.table.dropEvent(drop); drop.acceptProposedAction.assert_called_once()
        self.assertEqual([t['ref'] for t in self.dialog.values()],['goods:1',*refs[:2]])
        self.assertTrue(self.dialog.save_targets()); self.assertIsNone(self.window.worker)
        self.assertEqual([t['ref'] for t in MaterialStore(self.repo).definitions()['targets']],['goods:1',*refs[:2]])
        self.dialog.table.cellWidget(0,0).setChecked(False)
        self.assertEqual(self.dialog.table.item(0,6).text(),'已暂停')
        self.dialog.table.cellWidget(0,0).setChecked(True)
        self.assertEqual(self.dialog.table.item(0,6).text(),'按次数分配')

    def test_stock_condition_requires_amount_only_when_on_and_bulk_off_is_draft(self):
        from PyQt5.QtWidgets import QMessageBox
        self.dialog.add_target(A)
        condition=self.dialog.table.cellWidget(0,5); condition.setChecked(True)
        self.assertFalse(self.dialog.table.isColumnHidden(3))
        self.assertEqual(self.dialog.table.item(0,6).text(),'待设置数量')
        self.assertFalse(self.dialog.save_targets())
        self.dialog.amount_box(0).setValue(50)
        self.assertEqual(self.dialog.table.item(0,6).text(),'待达标')
        self.assertTrue(self.dialog.save_targets())
        self.dialog.add_target('goods:1'); self.dialog.show(); self.app.processEvents()
        self.assertTrue(self.dialog.amount_box(1).isHidden())
        self.assertFalse(self.dialog.amount_box(0).isHidden())
        self.dialog.resize(760,540); self.app.processEvents()
        self.assertGreaterEqual(self.dialog.table.columnWidth(1),240)
        self.assertGreater(self.dialog.table.horizontalScrollBar().maximum(),0)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): self.dialog.disable_stock_goals()
        self.assertFalse(self.dialog.values()[0]['stock_limit_enabled'])
        self.assertEqual(self.dialog.values()[0]['amount'],50)
        self.assertTrue(self.dialog.store.definitions()['targets'][0]['stock_limit_enabled'])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Discard): self.dialog.reject()
        self.assertTrue(self.dialog.store.definitions()['targets'][0]['stock_limit_enabled'])

    def test_frozen_counts_preview_and_shared_status_keep_independent_debt(self):
        from core.material_planner import plan
        self.dialog.add_target(A); self.dialog.save_targets()
        scope='plan:'+PlanStore(self.repo).today(); self.dialog.scope=scope
        store=self.dialog.store; snapshot=store.for_step(store.freeze(scope,scope),TASK)
        obs={'inventory':{},'balance':100,'stages':{'normal:4-1':{'status':'sweepable'}},'source':'game','at':1}
        store.observe(obs,snapshot); store.save_allocation(scope,'front',TASK,plan(snapshot,obs,{}))
        batch=store.prepare_batch(scope,TASK,'normal:4-1',6,[A],'front'); store.result_seen(batch,6); store.settle(batch,{})
        self.dialog.refresh_preview()
        self.assertEqual(self.dialog.preview.item(0,3).text(),'10')
        self.assertEqual(self.dialog.preview.item(0,4).text(),'6 / 4')
        self.dialog.tabs.setCurrentIndex(1); self.dialog.resize(760,540); self.dialog.show(); self.app.processEvents()
        self.assertLess(self.dialog.rule_target.geometry().right(),self.dialog.rule_stage.geometry().left())
        self.assertTrue(self.dialog.rect().contains(self.dialog.save_button.geometry()))
        event={'kind':'result','state':'succeeded','result':{'tasks':[dict(task_id=TASK,instance_id=TASK,status='PARTIAL',
            material_context=scope,material_allocation='front',remaining=[{'stage_id':'normal:4-1','count':4}])]}}
        self.window.routineInterface.on_event(event)
        self.assertEqual(self.window.routineInterface.cards[TASK].result.text(),'有余项 · 4 次')
        self.assertEqual(self.window._display_tasks(event)[0]['status'],'PARTIAL')
        batch=store.prepare_batch(scope,TASK,'normal:4-1',4,[A],'front'); store.result_seen(batch,4); store.settle(batch,{})
        self.window.routineInterface.on_event(event)
        self.assertEqual(self.window.routineInterface.cards[TASK].result.text(),'已完成')
        self.assertEqual(self.window._display_tasks(event)[0]['status'],'SUCCESS')

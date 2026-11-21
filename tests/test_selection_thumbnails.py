"""Offline thumbnail coverage and unchanged native selector values; never ADB."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import traceback
from unittest import TestCase

from core.paths import REPO_ROOT
from core.game_catalog import characters, stage_options, SHOP_ITEMS
from core.mad_features import MAP_LOCATIONS
from gui.selection_thumbnails import thumbnail_catalog, thumbnail_icon, thumbnail_entry


class SelectionThumbnails(TestCase):
    windows = []

    def setUp(self):
        from main import create_window
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.app, self.window = create_window(Path(temporary.name))
        type(self).app = self.app; self.windows.append(self.window)
        self.page = self.window.routineInterface
        self.addCleanup(self.window.close)

    def test_complete_catalog_assets_decode_and_ship_offline(self):
        from PyQt5.QtGui import QImageReader
        from scripts.build_release import selection_assets, source_files
        data = thumbnail_catalog()
        self.assertEqual(set(data['characters']), set(characters()))
        self.assertEqual(set(data['places']), {p for places in MAP_LOCATIONS.values() for p in places})
        self.assertEqual(set(data['shop']), set(SHOP_ITEMS))
        self.assertEqual([k for k, r in data['characters'].items() if r.get('status') == 'unmapped'], ['零'])
        self.assertEqual(data['characters']['维多利亚']['source_id'], 'CH0019')
        self.assertEqual(data['characters']['马内（泳装）']['source_id'], 'CH0010')
        files = selection_assets()
        self.assertEqual(len(files), 90)
        self.assertIn('gui/selection_thumbnails.py', source_files())
        for relative in files:
            with self.subTest(file=relative):
                self.assertTrue((REPO_ROOT/relative).is_file())
                if relative.endswith(('.webp', '.svg')):
                    self.assertFalse(QImageReader(str(REPO_ROOT/relative)).read().isNull())
        for kind in ('characters', 'places', 'shop'):
            for key in data[kind]:
                with self.subTest(kind=kind, key=key):
                    self.assertFalse(thumbnail_icon(kind, key).pixmap(48, 48).isNull())
        for task in ('mad.normal_sweep', 'mad.procurement_sweep', 'mad.flara_sweep'):
            for stage in stage_options(task):
                self.assertTrue(thumbnail_entry('stages', stage), stage)
                self.assertFalse(thumbnail_icon('stages', stage).pixmap(40, 40).isNull(), stage)

    def test_dating_thumbnails_keep_names_values_and_unknown_legacy_choices(self):
        from PyQt5.QtCore import Qt
        editor = self.page.editors['mad.dating']
        before = self.window.repository.load_config()['unfinished_tasks']
        original = editor.value()
        combo = editor.dating_character
        self.assertEqual([combo.itemData(i) for i in range(1, combo.count())], characters())
        for i in range(1, combo.count()):
            self.assertFalse(combo.itemIcon(i).pixmap(40, 40).isNull())
            self.assertTrue(combo.itemData(i, Qt.ToolTipRole))
        for map_id, choices in editor.location_choices.items():
            for choice in choices:
                self.assertEqual([choice.itemText(i) for i in range(choice.count())], list(MAP_LOCATIONS[map_id]))
                self.assertIn('<img', choice.toolTip())
                for i in range(choice.count()): self.assertFalse(choice.itemIcon(i).isNull())
        wanted = deepcopy(original)
        wanted.update(character='马内（泳装）', count=2)
        wanted['location_priority']['贝尔蒙特'] = ['菲尔哈莫尼修道院', '咖啡街', '宴会厅']
        editor.load(wanted)
        self.assertEqual(editor.value(), wanted)
        self.assertIn('马内（泳装）', combo.toolTip())
        self.assertTrue(self.page.save_changes())
        self.assertEqual(self.window.repository.load_config()['routine']['dating'], wanted)
        self.assertEqual(self.window.repository.load_config()['unfinished_tasks'], before)
        for name in ('零', '尚未适配的旧角色'):
            wanted['character'] = name; editor.load(wanted)
            self.assertEqual(editor.value(), wanted)
            self.assertIn('头像待补', combo.toolTip())
            self.assertFalse(combo.itemIcon(combo.currentIndex()).isNull())
        self.assertIsNone(self.window.worker)

    def test_shop_sweeps_and_plan_editor_share_thumbnails_without_new_parameters(self):
        from gui.fragments.routine import RoutineFragment
        for row, key in enumerate(SHOP_ITEMS):
            item = self.page.shop_table.item(row, 1)
            self.assertEqual(item.text(), SHOP_ITEMS[key]['title'])
            self.assertFalse(item.icon().isNull())
            self.assertIn('<img', item.toolTip())
        for key, selector in self.page.sweep_selectors.items():
            for row in range(selector.table.rowCount()):
                self.assertFalse(selector.table.item(row, 0).icon().isNull())
        for check in self.page.editors['mad.claim_all'].claim_checks.values():
            self.assertFalse(check.icon().isNull())
        spec = self.page.definition()
        plan = RoutineFragment(self.window.repository, self.window.theme, definition=spec)
        self.addCleanup(plan.close)
        self.assertEqual(plan.definition(), spec)
        combo = plan.editors['mad.dating'].dating_character
        self.assertFalse(combo.itemIcon(combo.findData('维多利亚')).isNull())
        self.assertEqual(plan.editors['mad.gold_shop'].value(), self.page.editors['mad.gold_shop'].value())

    def test_compact_dating_layout_keeps_long_place_names_readable(self):
        from PyQt5.QtGui import QFontMetrics
        from PyQt5.QtTest import QTest
        self.window.resize(980,680); self.window.show()
        self.page.open_settings('mad.dating'); QTest.qWait(50)
        editor = self.page.editors['mad.dating']
        for choices in editor.location_choices.values():
            for choice in choices:
                width = max(QFontMetrics(choice.font()).horizontalAdvance(choice.itemText(i)) for i in range(choice.count()))
                self.assertGreaterEqual(choice.width(), width + choice.iconSize().width() + 34)
            fields = [choice.parentWidget().geometry() for choice in choices]
            for i, first in enumerate(fields):
                for second in fields[i+1:]: self.assertFalse(first.intersects(second))

    def test_add_instruction_icon_picker_keeps_task_identity(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication, QComboBox
        before = set(self.page.editors)
        errors = []
        def choose():
            dialog = QApplication.activeModalWidget()
            try:
                combo = dialog.findChild(QComboBox)
                for i in range(combo.count()): self.assertFalse(combo.itemIcon(i).isNull())
                combo.setCurrentText('指定角色约会')
                dialog.accept()
            except Exception:
                errors.append(traceback.format_exc()); dialog.reject()
        QTimer.singleShot(0, choose); self.page._choose_task()
        self.assertEqual(errors, [])
        new = set(self.page.editors)-before
        self.assertEqual(len(new), 1)
        editor = self.page.editors[new.pop()]
        self.assertEqual(editor.task, 'mad.dating')
        self.assertEqual(editor.value(), self.page.editors['mad.dating'].value())

    def test_material_source_choice_exclusion_and_preview_icons(self):
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtWidgets import QApplication, QDialogButtonBox
        from PyQt5.QtTest import QTest
        from gui.fragments.materials import MaterialDialog
        from gui.widgets import CheckableListWidget
        task = 'mad.material_sweep'
        dialog = MaterialDialog(self.window.repository, self.window.theme, task, parent=self.window)
        dialog.add_target('item:80201'); self.assertTrue(dialog.save_targets())
        dialog.show(); self.app.processEvents(); dialog.table.selectRow(0)
        self.assertIsNone(dialog.rule_stage.itemData(0))
        for i in range(1, dialog.rule_stage.count()):
            self.assertFalse(dialog.rule_stage.itemIcon(i).isNull())
            self.assertTrue(dialog.rule_stage.itemData(i).startswith('normal:'))
        errors, selected = [], []
        def exclude():
            modal = QApplication.activeModalWidget()
            try:
                choices = modal.findChild(CheckableListWidget)
                for i in range(choices.count()): self.assertFalse(choices.item(i).icon().isNull())
                row = choices.item(0)
                selected.append(row.data(Qt.UserRole))
                QTest.mouseClick(choices.viewport(), Qt.LeftButton, pos=choices.visualItemRect(row).center())
                self.assertEqual(row.checkState(), Qt.Checked)
                QTest.keyClick(choices, Qt.Key_Space); self.assertEqual(row.checkState(), Qt.Unchecked)
                QTest.keyClick(choices, Qt.Key_Space); self.assertEqual(row.checkState(), Qt.Checked)
                modal.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
            except Exception:
                errors.append(traceback.format_exc()); modal.reject()
        QTimer.singleShot(0, exclude); dialog.exclude_sources()
        self.assertEqual(errors, [])
        self.assertEqual(dialog.values()[0]['excluded'], selected)
        self.assertTrue(dialog.save_targets())
        # Use another observed source; only the isolated fixture receives data.
        source = dialog.rule_stage.itemData(2)
        dialog.store.observe({'balance':100, 'stages':{source:{'status':'sweepable'}}, 'source':'game', 'at':1}, dialog.store.definitions())
        dialog.refresh_preview()
        self.assertGreater(dialog.preview.rowCount(), 0)
        self.assertFalse(dialog.preview.item(0, 0).icon().isNull())
        self.assertIsNone(self.window.worker)
        dialog.close(); dialog.deleteLater()

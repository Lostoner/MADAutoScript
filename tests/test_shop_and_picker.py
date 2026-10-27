"""Mouse-level picker regression and configured shop dispatch; no purchases."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import traceback
from core.paths import REPO_ROOT
from core.game_catalog import SHOP_ITEMS
from module import gold_shop


class PickerAndShopUI(TestCase):
    def test_three_pickers_and_shop_roundtrip(self):
        from main import create_window
        from PyQt5.QtCore import QTimer, Qt, QPoint
        from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QComboBox
        from PyQt5.QtTest import QTest
        from gui.widgets import CheckableListWidget
        with TemporaryDirectory(prefix='mad-picker-') as temporary:
            root = Path(temporary)
            app, window = create_window(root)
            type(self).qt_app = app
            page = window.routineInterface
            baseline = window.repository.load_config()
            events = window.repository.load_events()
            window.show()
            app.processEvents()
            try:
                for task, selector in page.sweep_selectors.items():
                    with self.subTest(task=task):
                        old = selector.value()
                        errors, picked = [], []
                        def interact():
                            dialog = QApplication.activeModalWidget()
                            try:
                                choices = dialog.findChild(CheckableListWidget)
                                combo = dialog.findChild(QComboBox)
                                button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
                                self.assertFalse(button.isEnabled())
                                available = [choices.item(i) for i in range(choices.count()) if choices.item(i).flags() & Qt.ItemIsEnabled]
                                for item in available[:2]:
                                    choices.scrollToItem(item)
                                    app.processEvents()
                                    rect = choices.visualItemRect(item)
                                    QTest.mouseClick(choices.viewport(), Qt.LeftButton, pos=rect.center())
                                    self.assertEqual(item.checkState(), Qt.Checked, 'row text must toggle')
                                    picked.append(item.data(Qt.UserRole))
                                item = available[1]
                                rect = choices.visualItemRect(item)
                                QTest.mouseClick(choices.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 8, rect.center().y()))
                                self.assertEqual(item.checkState(), Qt.Unchecked, 'checkbox area toggles once')
                                QTest.keyClick(choices, Qt.Key_Space)
                                self.assertEqual(item.checkState(), Qt.Checked)
                                combo.setCurrentIndex(combo.count() - 1)
                                combo.setCurrentIndex(0)
                                self.assertTrue(button.isEnabled())
                                self.assertIn('2', button.text())
                                QTest.mouseClick(button, Qt.LeftButton)
                            except Exception:
                                errors.append(traceback.format_exc())
                                dialog.reject()
                        QTimer.singleShot(0, interact)
                        selector.add_dialog()
                        self.assertEqual(errors, [])
                        self.assertEqual(selector.value(), old + [{'stage_id': key, 'count': 1} for key in picked])
                # Cancel the test sweep edits; retain the user's plans and progress.
                page.cancel_changes()
                self.assertEqual(window.repository.load_config(), baseline)
                self.assertEqual(list(page.shop_checks), list(SHOP_ITEMS))
                page.open_settings('mad.gold_shop')
                page.shop_checks['b_battle_log'].setChecked(True)
                page.shop_counts['b_battle_log'].setValue(3)
                page.shop_checks['sample_essence'].setChecked(True)
                page.shop_counts['sample_essence'].setValue(0)
                wanted = page._parameters()['gold_shop']['items']
                self.assertTrue(page.save_changes())
                self.assertEqual(window.repository.load_config()['unfinished_tasks'], baseline['unfinished_tasks'])
                self.assertEqual(window.repository.load_events(), events)
                app.processEvents()
                window.close()
                app.processEvents()
                _, window = create_window(root)
                self.assertEqual(window.routineInterface._parameters()['gold_shop']['items'], wanted)
                self.assertEqual(window.routineInterface.shop_counts['sample_essence'].value(), 0)
            finally:
                window.close()
                app.processEvents()


class ShopDispatch(TestCase):
    def worker(self, items, gold):
        worker = Mock(task_params={'gold_shop': {'items': items}})
        worker.line.side_effect = lambda area, *args: str(gold) if area == (910, 26, 999, 61) else '可购买10次'
        return worker

    def test_all_products_dispatch_and_normal_skips(self):
        items = [{'item_id': key, 'count': 2} for key in SHOP_ITEMS]
        worker = self.worker(items, 6460392)
        with patch.object(gold_shop, 'prepare_purchase', return_value=2) as prepare, patch.object(gold_shop, 'return_to_shop') as back, patch.object(gold_shop, 'co_detect', side_effect=['reward_popup', 'inadequate', *(['reward_popup'] * 4)]):
            self.assertTrue(gold_shop.implement(worker))
            self.assertEqual([c.args[1:] for c in prepare.call_args_list], [(p['item_id'], 2) for p in items])
            self.assertEqual(back.call_count, 6)
            worker.to_main_page.assert_not_called()
            self.assertEqual(len(worker.note.call_args.kwargs['purchased']), 5)
        worker = self.worker([{'item_id': 'a_battle_log', 'count': 1}, {'item_id': 'sample_essence', 'count': 'max'}], 20)
        with patch.object(gold_shop, 'prepare_purchase', return_value=2) as prepare, patch.object(gold_shop, 'return_to_shop'), patch.object(gold_shop, 'co_detect', return_value='reward_popup'):
            self.assertTrue(gold_shop.implement(worker))
            prepare.assert_called_once_with(worker, 'sample_essence', 2)
        worker = self.worker([{'item_id': 'c_battle_log', 'count': 1}], 100)
        worker.scan.return_value = [
            {'text': 'C级战斗日志', 'point': (1106, 526)},
            {'text': 'SOLD OUT', 'point': (1106, 481)},
            {'text': '售馨', 'point': (1106, 541)},
        ]
        with patch.object(gold_shop, 'co_detect', return_value='normal_shop'), patch.object(gold_shop, 'set_quantity') as quantity:
            self.assertTrue(gold_shop.implement(worker))
            quantity.assert_not_called()
            worker.click.assert_not_called()

    def test_purchase_follows_product_when_sold_out_cards_move(self):
        worker = Mock()
        # C has sold out and moved to the end; B and A have moved left.
        worker.scan.side_effect = [
            [{'text': 'B级战斗日志', 'point': (948, 291)},
             {'text': '可购买5次', 'point': (948, 306)}],
            [{'text': 'B级战斗日志', 'point': (790, 291)},
             {'text': '可购买5次', 'point': (790, 306)},
             {'text': 'A级战斗日志', 'point': (948, 291)},
             {'text': 'C级战斗日志', 'point': (1106, 526)},
             {'text': 'SOLDOUT', 'point': (1106, 481)}],
        ]
        with patch.object(gold_shop, 'co_detect', side_effect=['normal_shop', 'normal_shop', 'shop_target_dialog']), patch.object(gold_shop, 'set_quantity', return_value=5):
            self.assertEqual(gold_shop.prepare_purchase(worker, 'b_battle_log', 5), 5)
        self.assertEqual([c.args for c in worker.click.call_args_list], [(948, 291), (790, 291)])

"""Stage-list scrolling regressions; no device, account or OCR service needed."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from core.image import swipe_search_target_str
from module import normal_sweep


class StageSearch(TestCase):
    candidates = ['NORMAL5-' + str(n) for n in range(1, 13)]
    swipe = (512, 606, 512, 234, .5, .6)

    def worker(self, views):
        worker = SimpleNamespace(view=0, latest=0)
        worker.ocr = SimpleNamespace(text_list=Mock(side_effect=lambda *args: views[worker.latest]))
        worker.swipe = Mock(side_effect=lambda *args: setattr(worker, 'view', worker.view + 1))
        worker.update_screenshot_array = Mock(side_effect=lambda: setattr(worker, 'latest', worker.view))
        return worker

    def rows(self, *numbers):
        return [{'text': self.candidates[n - 1], 'point': (386, 100 + i * 61)}
                for i, n in enumerate(numbers)]

    def search(self, worker, number, swipes=3):
        return swipe_search_target_str(worker, possible_strs=self.candidates,
                                       target_str_index=number - 1, swipe_params=self.swipe,
                                       max_swipe_times=swipes)

    def test_target_above_visible_list_found_after_last_allowed_swipe(self):
        worker = self.worker([self.rows(3, 4, 5, 6, 7, 8, 9, 10, 11, 12), self.rows(1, 2, 3)])
        self.assertEqual(self.search(worker, 1, swipes=1), (386, 100))
        worker.swipe.assert_called_once_with(512, 234, 512, 606, .5, .6)
        worker.update_screenshot_array.assert_called_once_with()

    def test_target_below_list_uses_forward_swipe(self):
        worker = self.worker([self.rows(1, 2, 3), self.rows(10, 11, 12)])
        self.assertEqual(self.search(worker, 12, swipes=1), (386, 222))
        worker.swipe.assert_called_once_with(*self.swipe)

    def test_missing_target_stops_after_bounded_swipes_and_keeps_latest_view(self):
        worker = self.worker([self.rows(3, 4)] * 4)
        self.assertIsNone(self.search(worker, 1))
        self.assertEqual(worker.swipe.call_count, 3)
        self.assertEqual(worker.ocr.text_list.call_count, 4)
        self.assertEqual(worker.latest, worker.view)

    def test_current_view_is_checked_without_scrolling_and_matches_full_stage(self):
        worker = self.worker([self.rows(10, 1)])
        self.assertEqual(self.search(worker, 1, swipes=0), (386, 161))
        worker.swipe.assert_not_called()

    def test_unreadable_views_recover_on_final_swipe(self):
        worker = self.worker([[], [], [], self.rows(1, 2)])
        self.assertEqual(self.search(worker, 1), (386, 100))
        self.assertEqual([c.args[:4] for c in worker.swipe.call_args_list],
                         [(512, 606, 512, 234), (512, 234, 512, 606), (512, 606, 512, 234)])

    def test_normal_navigation_uses_zone_remembered_by_normal_not_hard(self):
        worker = SimpleNamespace(difficulty='HARD', zones={'HARD': 5, 'NORMAL': 12})
        worker.line = lambda *args: 'ZONE' + str(worker.zones[worker.difficulty])
        def detect(context, *, img_ends, **kwargs):
            if img_ends == 'normal_difficulty':
                context.difficulty = 'NORMAL'
            elif img_ends == 'normal_zone':
                # Switching HARD 5 -> NORMAL 12 must navigate left to NORMAL 5.
                self.assertEqual(kwargs['img_reactions']['normal_stage'], (103, 534))
                context.zones[context.difficulty] = context.target_zone
            return img_ends
        with patch.object(normal_sweep, 'co_detect', side_effect=detect):
            normal_sweep.navigate(worker, {'zone': 5})
        self.assertEqual((worker.difficulty, worker.zones['NORMAL']), ('NORMAL', 5))

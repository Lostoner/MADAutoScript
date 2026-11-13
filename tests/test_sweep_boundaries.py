"""Exercise the real quantity control and remaining-plan writes against a game double."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from core.config.repository import ProfileRepository
from module import sweep_utils as sweep


TASK = 'mad.normal_sweep'
A, B = 'normal:5-1', 'normal:5-2'
def plans(*rows):
    return [dict(stage_id=stage, count=count) for stage, count in rows]


class Game:
    def __init__(self, repo, balance):
        self.repository, self.balance = repo, balance
        self.limit = {}
        self.entered, self.settled = [], []
        self.current_instance_id = TASK
        self.logger, self.task_details = Mock(), {}
        self.read_header = True
        self.to_main_page = Mock()
        self.update_screenshot_array = Mock()

    def select(self, worker, task, stage):
        assert task == TASK
        self.stage = self.sweep_target = stage
        self.entered.append((self.current_instance_id, stage))
        return True

    def template(self, name):
        return self.limit.get(self.stage, 1000) > 0

    def detect(self, worker, *, img_ends, **kwargs):
        if 'sweep_confirm' in img_ends:
            assert self.balance >= 10, 'unexpected attempt after exhausting stamina'
            self.quantity = 1
            return 'sweep_confirm'
        if 'sweep_result' in img_ends:
            assert 0 < self.quantity <= self.maximum
            self.balance -= self.quantity * 10
            if self.stage in self.limit: self.limit[self.stage] -= self.quantity
            self.settled.append((self.current_instance_id, self.stage, self.quantity))
            return 'sweep_result'
        return img_ends

    @property
    def maximum(self):
        return min(self.balance // 10, self.limit.get(self.stage, 1000))

    def click(self, *point, count=1, **kwargs):
        if point == sweep.SWEEP_POINTS['max']: self.quantity = self.maximum
        elif point == sweep.SWEEP_POINTS['min']: self.quantity = 1
        elif point == sweep.SWEEP_POINTS['plus']: self.quantity = min(self.quantity + count, self.maximum)
        else: raise AssertionError(point)

    def line(self, area, *args):
        if area == (624,270,667,300): return str(self.quantity)
        if area == (499,354,593,389): return str(self.balance)
        if area == (686,354,778,389): return str(self.balance - self.quantity * 10)
        return f'{self.balance}/114' if self.read_header else ''

    def note(self, reason, **details):
        self.task_details = dict(reason=reason, **details)

    def run(self):
        with patch.object(sweep,'enter'), patch.object(sweep,'select_stage',side_effect=self.select), \
                patch.object(sweep,'return_to_list'), patch.object(sweep,'co_detect',side_effect=self.detect):
            assert sweep.run_plans(self, TASK, 'normal_stage', Mock())
        return self.task_details


class SweepBoundaries(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = ProfileRepository(Path(directory.name) / 'config/default')

    def test_partial_first_sweep_then_reward_then_independent_max_on_same_stage(self):
        tail = 'normal-after-rewards'
        self.repo.set_unfinished(TASK, plans((A,5),(B,1)))
        self.repo.set_unfinished(tail, plans((A,'max')))
        game = Game(self.repo, 27)
        game.read_header = False  # validated confirmation preview still ends this batch at 7
        first = game.run()
        self.assertEqual((first['status'],first['completed'],first['remaining']),
                         ('PARTIAL',2,plans((A,3),(B,1))))
        game.balance += 18  # simulated daily reward: 7 + 18 = 25
        game.current_instance_id = tail
        last = game.run()
        self.assertEqual((last['status'],last['completed'],game.balance),('SUCCESS',2,5))
        self.assertEqual(game.entered,[(TASK,A),(tail,A)])
        self.assertEqual(self.repo.load_config()['unfinished_tasks'][TASK], plans((A,3),(B,1)))
        self.assertEqual(game.run()['status'],'SKIPPED')

    def test_exactly_depleted_stops_before_next_stage_and_below_cost_skips_selection(self):
        self.repo.set_unfinished(TASK, plans((A,2),(B,3)))
        game = Game(self.repo,20)
        self.assertEqual(game.run()['remaining'],plans((B,3)))
        self.assertEqual(game.run()['completed'],0)
        self.assertEqual(game.entered,[(TASK,A)])
        self.assertEqual(game.settled,[(TASK,A,2)])

    def test_stage_max_can_be_limited_by_stage_not_stamina(self):
        for requested in ('max',5):
            with self.subTest(requested=requested):
                self.repo.set_unfinished(TASK, plans((A,requested),(B,1)))
                game = Game(self.repo,50)
                game.limit[A] = 2
                result = game.run()
                self.assertEqual(game.settled,[(TASK,A,2),(TASK,B,1)])
                self.assertEqual(result['remaining'],[] if requested=='max' else plans((A,3)))

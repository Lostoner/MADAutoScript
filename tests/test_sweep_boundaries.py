"""Exercise the real quantity control and remaining-plan writes against a game double."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from core.config.repository import ProfileRepository
from core.exception import FunctionCallTimeout, SweepResultUncertain
from core.Mad_thread import MadThread
from module import sweep_utils as sweep


TASK = 'mad.normal_sweep'
A, B = 'normal:5-1', 'normal:5-2'
def plans(*rows):
    return [dict(stage_id=stage, count=count) for stage, count in rows]


class Game:
    def __init__(self, repo, balance, task=TASK):
        self.repository, self.balance = repo, balance
        self.limit = {}
        self.entered, self.settled = [], []
        self.task = self.current_instance_id = task
        self.hard = task=='mad.hard_sweep'
        self.cost = 20 if self.hard else 10
        self.confirms = 0
        self.lose_result = False
        self.logger, self.task_details = Mock(), {}
        self.read_header = True
        self.to_main_page = Mock()
        self.update_screenshot_array = Mock()

    def select(self, worker, task, stage):
        assert task == self.task
        self.stage = self.sweep_target = stage
        self.entered.append((self.current_instance_id, stage))
        return self.limit.get(stage,1000) if self.hard else True

    def template(self, name):
        return self.limit.get(self.stage, 1000) > 0

    def detect(self, worker, *, img_ends, **kwargs):
        if 'sweep_confirm' in img_ends:
            assert self.balance >= self.cost, 'unexpected attempt after exhausting stamina'
            self.quantity = 1
            return 'sweep_confirm'
        if 'hard_count_readable' in img_ends: return 'hard_count_readable'
        if 'sweep_result' in img_ends:
            assert 0 < self.quantity <= self.maximum
            self.balance -= self.quantity * self.cost
            if self.stage in self.limit: self.limit[self.stage] -= self.quantity
            self.settled.append((self.current_instance_id, self.stage, self.quantity))
            if self.hard:
                assert 'img_reactions' not in kwargs and kwargs['handle_popups'] is False
                if self.lose_result: raise FunctionCallTimeout()
            return 'sweep_result'
        return img_ends

    @property
    def maximum(self):
        return min(self.balance // self.cost, self.limit.get(self.stage, 1000))

    def click(self, *point, count=1, **kwargs):
        if point == sweep.SWEEP_POINTS['max']: self.quantity = self.maximum
        elif point == sweep.SWEEP_POINTS['min']: self.quantity = 1
        elif point == sweep.SWEEP_POINTS['plus']: self.quantity = min(self.quantity + count, self.maximum)
        elif self.hard and point == sweep.SWEEP_POINTS['confirm']: self.confirms+=1
        elif self.hard and point == sweep.SWEEP_POINTS['open']: pass
        else: raise AssertionError(point)

    def line(self, area, *args):
        if area == (624,270,667,300): return str(self.quantity)
        if area == (499,354,593,389): return str(self.balance)
        if area == (686,354,778,389): return str(self.balance - self.quantity * self.cost)
        return f'{self.balance}/114' if self.read_header else ''

    def note(self, reason, **details):
        self.task_details = dict(reason=reason, **details)

    def run(self):
        with patch.object(sweep,'enter'), patch.object(sweep,'select_stage',side_effect=self.select), \
                patch.object(sweep,'return_to_list'), patch.object(sweep,'co_detect',side_effect=self.detect):
            assert sweep.run_plans(self, self.task, 'normal_stage', Mock())
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

    def test_hard_zero_fixed_and_native_max_have_separate_stage_and_stamina_limits(self):
        task='mad.hard_sweep'
        a,b,c,d=(f'hard:1-{n}' for n in (1,2,3,4))
        e='hard:2-1'
        self.repo.set_unfinished(task,plans((a,'max'),(b,5),(c,'max'),(d,5),(e,1)))
        g=Game(self.repo,165,task); g.limit={a:0,b:2,c:4}
        result=g.run()
        self.assertEqual(g.settled,[(task,b,2),(task,c,3),(task,d,3)])
        self.assertEqual((result['status'],result['completed'],g.balance,g.confirms),('PARTIAL',8,5,3))
        self.assertEqual(result['remaining'],plans((a,'max'),(b,3),(d,2),(e,1)))
        # Another copy sees the same game's exhausted stage, not a fresh allowance.
        self.repo.set_unfinished('tail',plans((b,'max'),(e,1)))
        g.current_instance_id='tail'; g.balance+=20
        self.assertEqual(g.run()['remaining'],plans((b,'max')))
        self.assertEqual(g.confirms,4)
        self.assertEqual(self.repo.load_config()['unfinished_tasks'][task],result['remaining'])

    def test_material_and_independent_hard_use_the_same_game_entries(self):
        from core.material_store import MaterialStore
        from module import material_sweep
        task='mad.hard_sweep'; a,b,c='hard:1-1','hard:8-1','hard:15-2'
        self.repo.set_unfinished(task,plans((a,2)))
        game=Game(self.repo,200,task); game.limit={a:3,b:3}
        game.run()
        self.assertEqual(game.limit[a],1)
        store=MaterialStore(self.repo)
        store.save_targets([{'ref':'item:29'}])
        store.freeze('round')
        game.current_instance_id='mad.material_sweep'
        game.task_params={'material_sweep':{'reserve':20}}
        game.guard=Mock()
        observer=material_sweep.Observer(game); observer.validate_version=Mock()
        observer.stock_on_stage=Mock()
        with patch.object(sweep,'enter'),patch.object(sweep,'select_stage',side_effect=game.select), \
                patch.object(material_sweep,'navigate_hard',side_effect=lambda w,option:option['zone']!=15) as navigate, \
                patch.object(sweep,'return_to_list'),patch.object(sweep,'co_detect',side_effect=game.detect):
            self.assertTrue(material_sweep.execute(game,store,'round',observer))
        self.assertEqual([call.args[1]['zone'] for call in navigate.call_args_list],[1,8,15,1,8])
        self.assertNotIn(('mad.material_sweep',c),game.entered)
        self.assertEqual(game.settled,[(task,a,2),('mad.material_sweep',a,1),('mad.material_sweep',b,3)])
        self.assertEqual((game.balance,game.limit,game.confirms),(80,{a:0,b:0},3))
        observer.stock_on_stage.assert_not_called()
        self.assertEqual(store.allocation('round','mad.material_sweep')['by_stage'],{a:1,b:3})
        game.current_instance_id='hard-tail'
        self.repo.set_unfinished('hard-tail',plans((a,'max'),(b,1)))
        game.run()
        self.assertEqual(game.confirms,3)
        self.assertEqual(self.repo.load_config()['unfinished_tasks']['hard-tail'],plans((a,'max'),(b,1)))

    def test_hard_confirmation_timeout_is_not_retried_by_the_ordinary_worker(self):
        task='mad.hard_sweep'; pending=plans(('hard:1-1',1))
        self.repo.set_unfinished(task,pending)
        g=Game(self.repo,80,task); g.lose_result=True; g.flag_run=True
        g.func_dict={task:lambda _:g.run()}
        with self.assertRaisesRegex(SweepResultUncertain,'结算不明'): MadThread.solve(g,task)
        self.assertEqual((g.confirms,g.balance),(1,60))
        self.assertEqual(self.repo.load_config()['unfinished_tasks'][task],pending)

    def test_hard_reset_offer_only_uses_a_cancel_button(self):
        w=Mock(sweep_page='normal_stage')
        w.line.return_value='是否消耗钻石重置进入次数？'
        self.assertFalse(sweep.hard_count_readable(w))
        w.scan.return_value=[{'text':'购买挑战次数','point':(640,240)},{'text':'取消','point':(480,501)},
                             {'text':'确认','point':(780,501)}]
        with patch.object(sweep,'co_detect',side_effect=['sweep_confirm','hard_attempt_dialog','normal_stage']):
            # The game offers a reset on MAX instead of returning a count.
            batch=sweep.start_sweep(w,'max',20,hard_limit=2)
            self.assertTrue(batch.stage_limited); self.assertEqual(batch.count,0)
            self.assertEqual([c.args for c in w.click.call_args_list],
                             [sweep.SWEEP_POINTS['open'],sweep.SWEEP_POINTS['max'],(480,501)])
            w.click.reset_mock(); w.scan.return_value.pop(1)
            with self.assertRaisesRegex(RuntimeError,'安全的退出按钮'): sweep.hard_denied(w,'hard_attempt_dialog')
            w.click.assert_not_called()

    def test_hard_native_zero_overrides_a_positive_row_allowance(self):
        w=Mock(sweep_page='normal_stage')
        w.line.side_effect=lambda area,*args:'0' if area==(624,270,667,300) else '80'
        with patch.object(sweep,'co_detect',side_effect=['sweep_confirm','hard_count_readable','hard_count_readable','normal_stage']):
            batch=sweep.start_sweep(w,'max',20,hard_limit=4)
        self.assertEqual((batch.count,batch.stage_limited),(0,True))
        self.assertEqual([c.args for c in w.click.call_args_list],
                         [sweep.SWEEP_POINTS['open'],sweep.SWEEP_POINTS['max'],sweep.SWEEP_POINTS['cancel']])

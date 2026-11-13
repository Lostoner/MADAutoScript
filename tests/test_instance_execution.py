"""Run the real scheduler, worker, sweep loop and profile across stop/restart."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from core.Mad_thread import MadThread
from core.config.repository import ProfileRepository, instance_params
from module import normal_sweep, sweep_utils


NORMAL, REWARD, TAIL = 'mad.normal_sweep', 'mad.claim_all', 'normal-after-reward'
STAGE, SECOND = 'normal:5-1', 'normal:5-2'


class InstanceExecution(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = ProfileRepository(Path(tmp.name)/'config/default')
        config = self.repo.load_config()
        self.events = self.repo.load_events()
        self.params = {e['instance_id']: deepcopy(instance_params(config,e)) for e in self.events}
        for event in self.events:
            event['enabled'] = event['instance_id'] in (NORMAL,REWARD)
        normal = next(e for e in self.events if e['instance_id']==NORMAL)
        self.events.append(dict(normal, instance_id=TAIL, event_name='领奖后清体力',follow_after=REWARD))
        self.params[NORMAL]={'plans':[dict(stage_id=STAGE,count=5),dict(stage_id=SECOND,count=2)]}
        self.params[TAIL]={'plans':[dict(stage_id=STAGE,count='max')]}
        self.repo.save_routine_instances(self.events,self.params)
        self.balance=27
        self.reward=18
        self.claims=0
        self.sweeps=[]

    def execute(self,*,stop_after=None,continuous=False,selection=None):
        def on_event(event):
            if (event['kind']=='task' and event.get('state')=='succeeded'
                    and event.get('instance_id')==stop_after):
                worker.request_stop()
        worker=MadThread(self.repo,on_event)
        worker.connect=worker.to_main_page=Mock()
        worker.func_dict['restart']=lambda w:True
        def claim(w):
            self.balance+=self.reward
            self.claims+=1
            return True
        def settle(w,requested,cost):
            count=self.balance//cost
            if requested!='max': count=min(count,requested)
            self.balance-=cost*count
            self.sweeps.append((w.current_instance_id,count))
            return sweep_utils.SweepBatch(count,self.balance)
        worker.func_dict[REWARD]=claim
        worker.template=Mock(return_value=True)
        worker.line=lambda *a: f'{self.balance}/114'
        worker.flag_run=True
        with patch.object(normal_sweep,'navigate'), patch.object(sweep_utils,'enter'), \
                patch.object(sweep_utils,'select_stage',return_value=True), \
                patch.object(sweep_utils,'start_sweep',side_effect=settle), \
                patch.object(sweep_utils,'return_to_list'):
            worker.thread_starter(continuous=continuous,task_ids=selection)
        self.assertIsNone(worker.last_result['error'])
        return worker.last_result

    def test_resume_after_claim_never_feeds_first_partial_from_new_reward(self):
        first=self.execute(stop_after=REWARD)
        self.assertEqual(first['status'],'stopped')
        self.assertEqual(self.balance,25)
        resumed=self.execute()
        self.assertEqual([(x['instance_id'],x['event_name']) for x in resumed['tasks']],[(TAIL,'领奖后清体力')])
        self.assertEqual((self.claims,self.sweeps,self.balance),(1,[(NORMAL,2),(TAIL,2)],5))
        remaining=self.repo.load_config()['unfinished_tasks']
        self.assertEqual(remaining[TAIL],[])
        self.assertEqual([p['count'] for p in remaining[NORMAL]],[3,2])

    def test_no_stamina_reward_and_old_cli_selector(self):
        self.reward=0
        result=self.execute()
        self.assertEqual([x['instance_id'] for x in result['tasks']],[NORMAL,REWARD,TAIL])
        self.assertEqual((self.sweeps,result['tasks'][-1]['completed']),([(NORMAL,2)],0))
        self.assertEqual([x['instance_id'] for x in self.execute(selection=[NORMAL])['tasks']],[NORMAL])

    def test_continuous_follower_resumes_without_repeating_parent(self):
        self.execute(continuous=True,stop_after=REWARD)
        result=self.execute(continuous=True,stop_after=TAIL)
        self.assertEqual([x['instance_id'] for x in result['tasks']],[TAIL])
        self.assertEqual(self.claims,1)
        self.assertEqual(self.sweeps,[(NORMAL,2),(TAIL,2)])

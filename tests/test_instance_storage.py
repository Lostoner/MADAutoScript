"""Profiles migrated in place, independent sweep progress, and paired-save recovery."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.config.repository import ConfigValidationError, ProfileRepository, instance_params
from core.runtime_state import atomic_json


class InstanceStorage(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo=ProfileRepository(Path(self.tmp.name)/'config/default')
        self.config=self.repo.load_config()
        self.events=self.repo.load_events()
        self.normal='mad.normal_sweep'
        self.event=next(e for e in self.events if e['func_name']==self.normal)
        self.params={e['instance_id']:deepcopy(instance_params(self.config,e)) for e in self.events}
        self.stage=self.params[self.normal]['plans'][0]['stage_id']

    def duplicate(self):
        self.events.append({**self.event,'instance_id':'tail','event_name':'领奖后清体力'})
        self.params['tail']={'plans':[{'stage_id':self.stage,'count':'max'}]}
        return self.repo.save_routine_instances(self.events,self.params)

    def test_copy_after_completion_and_independent_clocks(self):
        self.repo.complete_sweep(self.normal,self.stage,1)
        self.repo.save_events([{'func_name':self.normal,'next_tick':700}],fields={'next_tick'})
        config,events=self.duplicate()
        self.assertEqual(config['unfinished_tasks'][self.normal],[])
        self.assertEqual(config['unfinished_tasks']['tail'],self.params['tail']['plans'])
        self.assertEqual([e['next_tick'] for e in events if e['func_name']==self.normal],[700,0])
        self.repo.save_events([{'instance_id':'tail','next_tick':13}],fields={'next_tick'})
        self.repo.complete_sweep('tail',self.stage,3,finish_max=True)
        self.params[self.normal]['plans'][0]['count']=4
        config,events=self.repo.save_routine_instances(list(reversed(self.events)),self.params)
        self.assertEqual(config['unfinished_tasks']['tail'],[])
        self.assertEqual(config['unfinished_tasks'][self.normal][0]['count'],3)
        self.assertEqual([e['next_tick'] for e in events if e['func_name']==self.normal],[13,700])
        refreshed=self.repo.reset_progress()
        self.assertEqual(refreshed['unfinished_tasks']['tail'],self.params['tail']['plans'])
        self.assertEqual(refreshed['unfinished_tasks'][self.normal],self.params[self.normal]['plans'])
        config,_=self.repo.save_routine_instances(self.events[:-1],self.params)
        self.assertNotIn('tail',config['unfinished_tasks'])
        self.assertNotIn('tail',config['instance_params'])

    def test_schema5_migration_keeps_progress_and_explicit_reset(self):
        self.repo.complete_sweep(self.normal,self.stage,1)
        raw=self.repo.load_config()
        raw.pop('instance_params')
        raw['schema_version']=5
        raw['scheduling']['reset']={'enabled':False,'server_timezone':'UTC','reset_at':None}
        self.repo.config_path.write_text(json.dumps(raw),encoding='utf-8')
        old=[{k:v for k,v in e.items() if k!='instance_id'} for e in self.events]
        old[0]['post_task']=[self.normal]
        old[0]['next_tick']=888
        self.repo.event_path.write_text(json.dumps(old),encoding='utf-8')
        upgraded=self.repo.load_config()
        self.assertEqual(upgraded['scheduling'],raw['scheduling'])
        self.assertEqual(upgraded['unfinished_tasks'],raw['unfinished_tasks'])
        self.assertEqual(self.repo.load_events(),[dict(e,instance_id=e['func_name']) for e in old])
        self.assertEqual(self.repo.load_config(),upgraded)
        backup,=(self.repo.profile_dir/'backups').iterdir()
        self.assertEqual(json.loads((backup/'config.json').read_text('utf-8')),raw)
        self.assertEqual(json.loads((backup/'event.json').read_text('utf-8')),old)

    def test_interrupted_pair_is_replayed_before_scheduler_reads(self):
        def interrupted(path,data):
            if path==self.repo.event_path: raise OSError('simulated interrupted write')
            atomic_json(path,data)
        with patch('core.config.repository.atomic_json',side_effect=interrupted):
            with self.assertRaises(OSError): self.duplicate()
        reopened=ProfileRepository(self.repo.profile_dir)
        self.assertIn('tail',[e['instance_id'] for e in reopened.load_events()])
        self.assertEqual(reopened.load_config()['unfinished_tasks']['tail'],self.params['tail']['plans'])
        self.assertFalse(reopened.pending_path.exists())

    def test_adding_hard_to_an_old_queue_preserves_progress_and_rejects_normal_ids(self):
        from core.game_catalog import stage_options
        from core.tasks import function_table
        from module.hard_sweep import implement
        hard='mad.hard_sweep'
        catalog=stage_options(hard)
        self.assertEqual({k:v['cost'] for k,v in catalog.items()},
                         {f'hard:{z}-{n}':20 for z in range(1,16) for n in range(1,5)})
        self.assertIs(function_table()[hard],implement)
        base=next(e for e in self.events if e['func_name']==hard)
        self.assertFalse(base['enabled']); self.assertEqual(self.params.pop(hard),{'plans':[]})
        events=[e for e in self.events if e is not base]
        self.repo.complete_sweep(self.normal,self.stage,1)
        old=self.repo.load_config(); old['routine'].pop('hard_sweep'); old['unfinished_tasks'].pop(hard)
        atomic_json(self.repo.config_path,old); atomic_json(self.repo.event_path,events)
        self.assertEqual(self.repo.load_events(),events)
        self.assertEqual(self.repo.load_config()['unfinished_tasks'],old['unfinished_tasks'])
        self.assertEqual(json.loads(self.repo.config_path.read_text('utf-8')),old)
        plans=[{'stage_id':'hard:5-1','count':2}]
        self.params.update({hard:{'plans':plans},'tail':{'plans':plans}})
        events+= [base,dict(base,instance_id='tail',event_name='尾扫')]
        self.repo.save_routine_instances(events,self.params)
        self.repo.complete_sweep(hard,'hard:5-1',1)
        saved=ProfileRepository(self.repo.profile_dir).load_config()
        self.assertEqual(saved['unfinished_tasks'],dict(old['unfinished_tasks'],**{
            hard:[{'stage_id':'hard:5-1','count':1}],'tail':plans}))
        for bad in ('normal:5-1','hard:5-5'):
            with self.assertRaisesRegex(ConfigValidationError,'HARD'):
                self.repo.patch_config({'routine':{'hard_sweep':{'plans':[{'stage_id':bad,'count':1}]}}})
        self.assertEqual(self.repo.load_config(),saved)

    def test_validate_copies_and_follow_targets_before_saving(self):
        self.duplicate()
        self.events[-1]['follow_after']='mad.claim_all'
        self.params['tail']['plans']*=2
        with self.assertRaises(ConfigValidationError):
            self.repo.save_routine_instances(self.events,self.params)
        self.params['tail']['plans'].pop()
        self.repo.save_routine_instances(self.events,self.params)
        self.events[-1]['follow_after']='tail'
        with self.assertRaises(ConfigValidationError):
            self.repo.save_routine_instances(self.events,self.params)
        self.assertEqual(self.repo.load_events()[-1]['follow_after'],'mad.claim_all')

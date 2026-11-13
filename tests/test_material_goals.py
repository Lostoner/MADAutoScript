"""Material intent, greedy plans and receipt recovery without a device."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from core.config.repository import ProfileRepository
from core.material_store import MaterialStore, TASK, MANUAL_PREVIEW_TTL
from core.material_planner import catalog, plan
from core.plan_store import PlanStore
from core.plan_runner import PlanPass
from core.Mad_thread import MadThread
from module.material_sweep import exact_inventory, execute, Observer
from module import sweep_utils as sweep

A, B = 'item:80201', 'item:80202'
S, T = 'normal:4-1', 'normal:4-2'


def target(ref=A, amount=10, **changes):
    result = dict(ref=ref,amount=amount,enabled=True,priority=1,excluded=[],version='v1')
    result.update(changes)
    return result


def fixture():
    data = {'version':'test','items':{r:{'name':r,'sources':[S,T]} for r in (A,B)},
            'stages':{s:{'cost':10,'drops':{r:[{'amount':[1,0],'chance':1}] for r in (A,B)}} for s in (S,T)}}
    snapshot = {'targets':[target(),target(B)],'catalog_version':'test'}
    obs = {'inventory':{A:0,B:0},'stages':{s:{'status':'sweepable'} for s in (S,T)},'balance':100}
    return data,snapshot,obs


class PlannerTests(TestCase):
    def test_catalog_has_only_repeat_normal_public_data(self):
        data=catalog()
        self.assertEqual((len(data['items']),len(data['stages'])),(61,180))
        self.assertEqual(sum(i['verification']=='public_table_pending_live' for i in data['items'].values()),13)
        self.assertNotIn('item:80601',data['items'])
        from core.game_catalog import stage_options
        self.assertEqual(set(data['stages']),set(stage_options('mad.normal_sweep')))

    def test_exact_inventory_requires_identity_and_unabbreviated_number(self):
        self.assertEqual(exact_inventory(['T2耳环兑换券','拥有数量：0'],'T2耳环兑换券'),0)
        self.assertEqual(exact_inventory(['T2耳环兑换券','拥有数量：1,234'],'T2耳环兑换券'),1234)
        for lines in (['其他素材','拥有数量：15'],['T2耳环兑换券','拥有数量：1.2K'],
                      ['T2耳环兑换券','拥有数量：1.0'],['T2耳环兑换券','拥有数量：1,2']):
            self.assertIsNone(exact_inventory(lines,'T2耳环兑换券'))

    def test_unknown_stock_unchecked_stage_and_reserve_do_not_spend(self):
        d,s,o=fixture(); o['inventory'][A]=None; o['stages'][S]['status']='unavailable'; o['stages'][T]['status']='unchecked'
        p=plan(s,o,{},data=d)
        self.assertEqual(p['rows'],[]); self.assertEqual(p['waiting'][A],'库存待同步')
        d,s,o=fixture(); p=plan(s,o,{},reserve=95,data=d)
        self.assertFalse(p['rows'])
        o['inventory']={A:10,B:10}; self.assertEqual(plan(s,o,{},data=d),{'rows':[],'waiting':{}})

    def test_shared_drop_greedy_is_stable_and_never_writes_inventory(self):
        d,s,o=fixture(); before=deepcopy(o)
        p=plan(s,o,{},data=d)
        self.assertEqual(p['rows'][0]['refs'],[A,B]); self.assertEqual(p['rows'][0]['count'],10)
        self.assertEqual(p['rows'][0]['batch_count'],5)
        self.assertEqual(p,plan(s,o,{},data=d)); self.assertEqual(o,before)
        o['inventory']={A:9,B:9}; self.assertEqual(plan(s,o,{},data=d)['rows'][0]['batch_count'],1)

    def test_manual_cap_is_per_target_across_stages_and_consumed_on_resume(self):
        d,s,o=fixture(); s['targets']=[target()]
        rules={A:{'stage':None,'max_runs':2}}
        p=plan(s,o,{},rules,data=d)
        self.assertEqual(sum(r['count'] for r in p['rows']),2)
        p=plan(s,o,{},rules,{A:2},data=d)
        self.assertFalse(p['rows']); self.assertIn('上限',p['waiting'][A])
        rules[A]['stage']=T
        self.assertEqual(plan(s,o,{},rules,data=d)['rows'][0]['stage_id'],T)

    def test_priority_uses_gap_fraction_not_raw_units(self):
        d,s,o=fixture()
        s['targets'][1]['priority']=2
        d['stages'][S]['drops']={A:[{'amount':[10000,0],'chance':1}]}
        d['stages'][T]['drops']={B:[{'amount':[1,0],'chance':1}]}
        self.assertEqual(plan(s,o,{},data=d)['rows'][0]['stage_id'],T)

    def test_source_only_never_invents_total_yield_and_exclusions_apply(self):
        d,s,o=fixture(); s['targets']=[target()]
        for stage in d['stages'].values(): stage['drops'][A][0]['chance']=None
        p=plan(s,o,{},data=d)
        self.assertEqual((len(p['rows']),p['rows'][0]['count'],p['rows'][0]['estimated'][A]),(1,1,None))
        s['targets'][0]['excluded']=[S,T]
        self.assertFalse(plan(s,o,{},data=d)['rows'])

    def test_zero_chance_or_changed_catalog_cannot_generate_spending(self):
        d,s,o=fixture(); s['targets']=[target()]
        for stage in d['stages'].values(): stage['drops'][A][0]['chance']=0
        self.assertFalse(plan(s,o,{},data=d)['rows'])
        s['catalog_version']='old'
        self.assertIn('目录版本',plan(s,o,{},data=d)['waiting'][A])

    def test_release_inventory_includes_feature_but_no_account_snapshots(self):
        from scripts.build_release import source_files, PUBLIC
        files=set(source_files()+PUBLIC)
        self.assertTrue({'core/material_store.py','core/material_planner.py','module/material_sweep.py',
                         'gui/fragments/materials.py','src/material_catalog.json','docs/MATERIAL_GOALS.md'} <= files)
        self.assertFalse(any(f.startswith(('artifacts/','state/','config/')) for f in files))
        self.assertNotIn('inventory',catalog())


class StorageTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.repo=ProfileRepository(Path(tmp.name)/'config/default'); self.repo.load_config()
        self.store=MaterialStore(self.repo)
        self.store.save_targets([target()])

    def observation(self, amount):
        return {'inventory':{A:amount},'stages':{S:{'status':'sweepable'}},'balance':100,'at':1,'source':'game'}

    def test_completion_is_versioned_sticky_and_not_reset_by_round_or_day(self):
        old=self.store.freeze('one'); self.store.observe(self.observation(10),old)
        self.store.observe(self.observation(0),old); self.repo.reset_progress()
        self.assertFalse(self.store.remaining(self.store.freeze('two')))
        draft=self.store.definitions(); draft['targets'][0]['priority']=2
        self.store.save_targets(draft['targets']); self.assertFalse(self.store.remaining(self.store.freeze('three')))
        draft=self.store.definitions(); draft['targets'][0]['amount']=20
        new=self.store.save_targets(draft['targets'])
        self.assertNotEqual(new['targets'][0]['version'],old['targets'][0]['version'])
        self.assertTrue(self.store.remaining(self.store.freeze('four')))
        self.assertFalse(self.store.remaining(old))

    def test_temporary_overrides_do_not_copy_to_next_round(self):
        self.store.set_adjustments('routine','tail',{A:{'stage':S,'max_runs':2}})
        first=self.store.freeze('one'); second=self.store.freeze('two')
        self.assertEqual(first['rules']['tail'][A]['max_runs'],2)
        self.assertEqual(second['rules'],{})

    def test_batch_identity_applies_once_and_unknown_requires_disposition(self):
        snap=self.store.freeze('one')
        batch=self.store.prepare_batch('one','tail',S,2,[A])
        with self.assertRaises(RuntimeError): self.store.settle(batch,self.observation(10))
        with self.assertRaises(RuntimeError): self.store.prepare_batch('one','other',S,1,[A])
        self.store.result_seen(batch,2); self.assertTrue(self.store.settle(batch,self.observation(3)))
        self.assertFalse(self.store.settle(batch,self.observation(99)))
        self.assertEqual(self.store.state()['rounds']['one']['used']['tail'][A],2)
        self.assertEqual(self.store.state()['observation']['inventory'][A],3)
        self.store.prepare_batch('one','tail',S,2,[A]); self.store.resolve_pending(True)
        state=self.store.state(); self.assertIn('tail',state['rounds']['one']['blocked'])
        self.assertIsNone(state['rounds']['one']['receipts'][-1]['count'])
        self.assertTrue(self.store.remaining(snap))

    def test_manual_inventory_does_not_claim_permanent_completion(self):
        snap=self.store.freeze('one'); self.store.correct_inventory(A,50)
        self.assertTrue(self.store.remaining(snap))
        self.assertEqual(self.store.state()['observation']['source'],'manual')
        at=self.store.state()['observation']['manual'][A]
        self.assertEqual(self.store.preview_observation(at+1)['inventory'][A],50)
        self.assertIsNone(self.store.preview_observation(at+MANUAL_PREVIEW_TTL+1)['inventory'][A])

    def test_pause_reopen_and_order_preserve_the_intended_completion_version(self):
        snap=self.store.freeze('one'); self.store.observe(self.observation(10),snap)
        goals=self.store.definitions()['targets']; goals[0]['enabled']=False
        self.store.save_targets(goals); goals[0]['enabled']=True
        self.store.save_targets(goals)
        self.assertFalse(self.store.remaining(self.store.freeze('two')))
        goals[0]['reopen']=True; self.store.save_targets(goals)
        self.assertTrue(self.store.remaining(self.store.freeze('three')))

    def test_plan_freezes_intent_and_uses_original_profile_state(self):
        plans=PlanStore(self.repo); day=plans.today(); draft=plans.load()
        definition=plans.from_daily()
        draft['days'][day]={'kind':'tasks','routine':definition}
        plans.save(draft); daily=plans.day_repository(day)
        first=self.store.state()['rounds']['plan:'+day]['snapshot']
        self.store.save_targets([target(amount=50)])
        plans.day_repository(day)
        self.assertEqual(self.store.state()['rounds']['plan:'+day]['snapshot'],first)
        policy=PlanPass(plans,day,daily,plans.clock)
        worker=MadThread(daily,plan_pass=policy)
        self.assertEqual(worker.material_repository.profile_dir,self.repo.profile_dir)
        self.store.observe(self.observation(10),first)
        policy.tasks=[{'instance_id':'front','status':'PARTIAL','task_id':TASK}, {'instance_id':'tail','status':'SUCCESS','task_id':TASK}]
        policy.finish_pass()
        self.assertEqual(plans.record(day)['status'],'completed')
        self.assertTrue(self.store.remaining({'targets':self.store.definitions()['targets']}))

    def test_plan_manual_unknown_keeps_goal_partial_and_resume_cannot_refill_quota(self):
        from core.plan_runner import PlanRunner
        plans=PlanStore(self.repo); day=plans.today(); draft=plans.load()
        draft['days'][day]={'kind':'tasks','routine':plans.from_daily()}; plans.save(draft)
        daily=plans.day_repository(day); policy=PlanPass(plans,day,daily,plans.clock)
        token=['main',TASK,1]; policy.group(TASK,0)
        policy.begin_step(TASK,token,{'instance_id':TASK,'task_id':TASK,'event_name':'素材'})
        self.store.prepare_batch('plan:'+day,TASK,S,2,[A])
        policy.ended({'error':'connection lost','run_dir':'test'})
        self.assertEqual(plans.record(day)['status'],'needs_review')
        runner=PlanRunner(plans,SimpleNamespace(worker=None,emit=Mock(),repository=self.repo))
        self.assertTrue(runner.resolve_current(True))
        resumed=PlanPass(plans,day,daily,plans.clock); resumed.finish_pass()
        self.assertEqual(plans.record(day)['remaining'],[TASK])
        self.assertEqual(plans.record(day)['status'],'partial')
        retry=PlanPass(plans,day,daily,plans.clock,only_remaining=True)
        self.assertNotIn(token,retry.groups[TASK]['steps'])
        self.assertIn(TASK,self.store.state()['rounds']['plan:'+day]['blocked'])


class ExecutionTests(TestCase):
    setUp = StorageTests.setUp

    def run_material(self, stock=0, balance=100, cap=None):
        if cap is not None: self.store.set_adjustments('routine','front',{A:{'stage':S,'max_runs':cap}})
        self.snapshot=self.store.freeze('round')
        self.worker=SimpleNamespace(current_instance_id='front',task_params={'material_sweep':{'reserve':0}},
                                    guard=Mock(),plan_pass=None,note=Mock(),click=Mock(),to_main_page=Mock())
        self.observer=Mock()
        self.stock,self.balance=stock,balance
        self.calls=[]
        def observe(*_):
            return {'source':'game','at':1,'inventory':{A:self.stock},'balance':self.balance,'stages':{S:{'status':'sweepable'}}}
        self.observer.collect.side_effect=observe
        self.observer.after_batch.side_effect=observe
        self.observer.select.return_value=True
        def start(w,count,cost,*,before_confirm):
            actual=min(count,self.balance//cost)
            if not actual:return sweep.SweepBatch()
            before_confirm(actual,self.balance-actual*cost)
            self.calls.append(actual); self.balance-=actual*cost; self.stock+=actual
            return sweep.SweepBatch(actual,self.balance)
        self.start=start
        return self.continue_material()

    def continue_material(self):
        with patch.object(sweep,'start_sweep',side_effect=self.start),patch.object(sweep,'return_to_list'):
            return execute(self.worker,self.store,'round',self.observer)

    def test_already_satisfied_zero_spend_and_receipt_not_estimate(self):
        self.run_material(stock=20)
        self.assertEqual(self.calls,[]); self.assertFalse(self.store.remaining(self.snapshot))
        self.assertEqual(self.worker.note.call_args.kwargs['status'],'SKIPPED')

    def test_front_reward_tail_share_stock_and_manual_limit_does_not_replenish(self):
        self.run_material(stock=0,balance=100,cap=2)
        self.assertEqual(sum(self.calls),2)
        self.continue_material(); self.assertEqual(sum(self.calls),2)
        self.stock=9; self.balance=10; self.worker.current_instance_id='tail'
        self.continue_material()
        self.assertEqual(sum(self.calls),3); self.assertFalse(self.store.remaining(self.snapshot))

    def test_resource_boundary_consumes_only_affordable_then_continues_task_chain(self):
        self.run_material(stock=0,balance=27)
        self.assertEqual((sum(self.calls),self.balance),(2,7))
        self.assertEqual(self.worker.note.call_args.kwargs['status'],'PARTIAL')

    def test_unknown_receipt_blocks_both_new_round_and_new_instruction(self):
        self.snapshot=self.store.freeze('round'); self.store.prepare_batch('round','front',S,2,[A])
        self.store.freeze('other')
        worker=SimpleNamespace(current_instance_id='tail')
        observer=Mock()
        with self.assertRaisesRegex(RuntimeError,'待核对'):execute(worker,self.store,'other',observer)
        observer.collect.assert_not_called()

    def test_visible_result_survives_failure_before_inventory_read(self):
        self.run_material(stock=9,balance=10)
        # A separate pending receipt whose result was displayed before a crash.
        self.store.save_targets([target(amount=20)])
        self.store.freeze('new')
        batch=self.store.prepare_batch('new','front',S,1,[A]);self.store.result_seen(batch,1)
        self.worker.current_instance_id='front'; self.balance=0; self.stock=11
        with patch.object(sweep,'start_sweep',side_effect=self.start):
            execute(self.worker,self.store,'new',self.observer)
        self.assertIsNone(self.store.state()['pending'])
        self.assertEqual(self.store.state()['rounds']['new']['used']['front'][A],1)

    def test_failure_after_result_never_confirms_the_batch_again(self):
        self.run_material(stock=0,balance=0)
        self.balance=10; self.stock=9
        observe=self.observer.after_batch.side_effect
        self.observer.after_batch.side_effect=RuntimeError('inventory read interrupted')
        with self.assertRaisesRegex(RuntimeError,'interrupted'): self.continue_material()
        self.assertEqual(self.store.state()['pending']['phase'],'result_observed')
        self.assertEqual(self.calls,[1])
        self.observer.after_batch.side_effect=observe
        self.continue_material()
        self.assertEqual(self.calls,[1]); self.assertIsNone(self.store.state()['pending'])
        self.assertFalse(self.store.remaining(self.snapshot))

    def test_observer_requires_matched_game_version_and_marks_locked_sources(self):
        w=SimpleNamespace(config={'game':{'channel':'onestore'}},connection=Mock(),guard=Mock())
        observer=Observer(w); w.connection.shell.return_value='versionName=0.0.0'
        with self.assertRaisesRegex(RuntimeError,'版本'): observer.collect({'targets':[target()]})
        w.connection.shell.return_value='versionName='+catalog()['game_version']
        observer.select=Mock(return_value=False)
        observer.stock_on_stage=Mock()
        observed=observer.collect({'targets':[target()]})
        self.assertIsNone(observed['inventory'][A]); self.assertIsNone(observed['balance'])
        self.assertTrue(all(s['status']=='unavailable' for s in observed['stages'].values()))
        observer.stock_on_stage.assert_not_called()

    def test_progress_navigation_requires_each_zone_transition(self):
        from module.normal_sweep import navigate
        for lines,expected,clicks in ((['ZONE1','ZONE2','ZONE3'],True,2),
                                      (['ZONE1','ZONE1'],False,1),(['ZONE1','ZONE3'],False,1)):
            with self.subTest(lines=lines):
                w=SimpleNamespace(line=Mock(side_effect=lines),click=Mock(),update_screenshot_array=Mock())
                with patch('module.normal_sweep.co_detect'):
                    self.assertEqual(navigate(w,{'zone':3},check_locked=True),expected)
                self.assertEqual(w.click.call_count,clicks)

    def test_readonly_sync_uses_worker_lease_but_does_not_write_daily_run_receipt(self):
        resources=Mock(); lease=Mock(); resources.acquire_execution.return_value=lease
        w=MadThread(self.repo,resources=resources,material_sync=True)
        w.connect=Mock(); w.func_dict['restart']=lambda _:True; w.flag_run=True
        with patch('module.material_sweep.sync') as sync:
            w.thread_starter()
        sync.assert_called_once_with(w); resources.acquire_execution.assert_called_once(); lease.unlock.assert_called_once()
        self.assertEqual(w.last_result['status'],'succeeded')
        self.assertFalse((self.repo.data_root/'state'/self.repo.profile_id/'last-run.json').exists())

    def test_confirmation_callback_precedes_single_consumption_click(self):
        events=[]; w=SimpleNamespace(sweep_page='normal_stage',sweep_target=S,logger=Mock(),update_screenshot_array=Mock())
        w.click=lambda *p,**k:events.append(('click',p))
        w.line=lambda area,*_: '1' if area==(624,270,667,300) else '20' if area==(499,354,593,389) else '10'
        def detect(*_,img_ends,**kwargs):
            if isinstance(img_ends,list): return 'sweep_result' if 'sweep_result' in img_ends else 'sweep_confirm'
            return img_ends
        with patch.object(sweep,'co_detect',side_effect=detect):
            result=sweep.start_sweep(w,5,10,before_confirm=lambda n,b:events.append(('persist',n)))
        confirms=[i for i,v in enumerate(events) if v==('click',sweep.SWEEP_POINTS['confirm'])]
        self.assertEqual(len(confirms),1)
        self.assertLess(events.index(('persist',1)),confirms[0]); self.assertEqual(result.count,1)

"""Weighted allocations, preserved legacy intent and exact-count recovery. No device."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from core.config.repository import ProfileRepository
from core.material_planner import plan
from core.material_store import MaterialStore
from core.runtime_state import atomic_json
from module.material_sweep import execute, Observer
from module import sweep_utils as sweep

A,B,C,D='item:80201','item:80205','item:80202','goods:1'
S,T,U='normal:4-1','normal:5-1','normal:6-1'


def target(ref, **values):
    return dict(dict(ref=ref,amount=None,version='v1',stock_limit_enabled=False,enabled=True,excluded=[]),**values)


def fixture(shared=False):
    drops={S:[A,C,D],T:[B,D]} if shared else {S:[A],T:[B],U:[C]}
    refs=[A,B,C,D] if shared else [A,B,C]
    data={'version':'test','channel':'onestore','game_version':'test',
          'items':{r:{'name':r,'sources':[s for s,rs in drops.items() if r in rs]} for r in refs},
          'stages':{s:{'cost':10,'drops':{r:[{'chance':1,'amount':[1,0]}] for r in rs}} for s,rs in drops.items()}}
    snapshot={'allocation_version':2,'catalog_version':'test','targets':[target(r) for r in refs],'rules':{}}
    obs={'inventory':{},'balance':100,'source':'game','at':1,'stages':{s:{'status':'sweepable'} for s in drops}}
    return data,snapshot,obs


class WeightedPlannerTests(TestCase):
    def test_hamilton_counts_rounding_and_no_mutation(self):
        data,snapshot,obs=fixture(); before=deepcopy((snapshot,obs))
        for balance,expected in [(100,[5,3,2]),(20,[1,1]),(0,[])]:
            obs['balance']=balance
            rows=plan(snapshot,obs,{},data=data)['rows']
            self.assertEqual([r['count'] for r in rows],expected)
            self.assertLessEqual(sum(r['cost'] for r in rows),balance)
        obs['balance']=100
        self.assertEqual((snapshot,obs),before)
        self.assertEqual(plan(snapshot,obs,{},data=data),plan(snapshot,obs,{},data=data))

    def test_shared_credit_never_propagates_priority_to_other_stage(self):
        data,snapshot,obs=fixture(True); obs['balance']=160
        rows=plan(snapshot,obs,{},reserve=20,data=data)['rows']
        self.assertEqual([(r['stage_id'],r['weight'],r['count']) for r in rows],[(S,4,8),(T,3,6)])
        self.assertEqual(len({r['stage_id'] for r in rows}),len(rows))

    def test_actual_catalog_matches_ear_hat_neck_credit_example(self):
        from core.material_planner import catalog
        data=catalog()
        snapshot={'allocation_version':2,'catalog_version':data['version'],'targets':[target(r) for r in (A,B,C,D)]}
        obs={'balance':160,'stages':{s:{'status':'sweepable'} for s in (S,T)}}
        rows=plan(snapshot,obs,{},reserve=20)['rows']
        self.assertEqual([(r['stage_id'],r['weight'],r['count']) for r in rows],[(S,4,8),(T,3,6)])

    def test_amount_probability_and_inventory_do_not_drive_unlimited_goals(self):
        data,snapshot,obs=fixture(); before=plan(snapshot,obs,{},data=data)
        obs['inventory']={A:99999,B:0,C:1234}
        for stage in data['stages'].values():
            for rows in stage['drops'].values(): rows[0].update(amount=[999,1000],chance=None)
        self.assertEqual(plan(snapshot,obs,{},data=data),before)

    def test_optional_unknown_stock_only_excludes_affected_material(self):
        data,snapshot,obs=fixture()
        snapshot['targets'][0].update(stock_limit_enabled=True,amount=50)
        result=plan(snapshot,obs,{},data=data)
        self.assertTrue(result['waiting_data']); self.assertIn('库存',result['waiting'][A])
        self.assertEqual([r['count'] for r in result['rows']],[7,3])
        self.assertEqual(sum(r['count'] for r in result['rows']),10)

    def test_stock_only_continuation_keeps_original_weights_without_pure_goal(self):
        data,snapshot,obs=fixture(); snapshot['inventory_only']=True
        for t in (snapshot['targets'][0],snapshot['targets'][2]): t.update(stock_limit_enabled=True,amount=100)
        obs.update(inventory={A:0,C:0},balance=80)
        rows=plan(snapshot,obs,{},data=data)['rows']
        self.assertEqual([(r['stage_id'],r['weight'],r['count']) for r in rows],[(S,3,6),(U,1,2)])

    def test_caps_pin_and_excluded_incidental_drop_do_not_gain_priority(self):
        data,snapshot,obs=fixture(True)
        rules={A:{'max_runs':0,'stage':None},C:{'stage':S,'max_runs':2}}
        rows=plan(snapshot,obs,{},rules,data=data)['rows']
        self.assertNotIn(A,[r for row in rows for r in row['refs']])
        self.assertLessEqual(sum(row['count'] for row in rows if C in row['refs']),10)
        # An exhausted goal no longer drives allocation, but co-drops can remain.
        result=plan(snapshot,obs,{},rules,{C:2},data=data)
        self.assertNotIn(C,[r for row in result['rows'] for r in row['refs']])
        snapshot['targets'][1]['excluded']=[T]
        result=plan(snapshot,obs,{},rules,data=data)
        self.assertNotIn(T,[row['stage_id'] for row in result['rows']])

    def test_unavailable_and_missing_data_are_distinct_and_pauses_keep_rank(self):
        data,snapshot,obs=fixture()
        obs.update(balance=None,stages={s:{'status':'unavailable'} for s in data['stages']})
        self.assertFalse(plan(snapshot,obs,{},data=data)['waiting_data'])
        obs['stages'].pop(S)
        self.assertTrue(plan(snapshot,obs,{},data=data)['waiting_data'])
        snapshot['targets'][0]['enabled']=False
        obs.update(balance=100,stages={s:{'status':'sweepable'} for s in data['stages']})
        rows=plan(snapshot,obs,{},data=data)['rows']
        self.assertEqual([(r['weight'],r['count']) for r in rows],[(2,7),(1,3)])

    def test_unspendable_stamina_does_not_distort_hamilton_remainders(self):
        data,snapshot,obs=fixture()
        for ref,stage in [('item:80208','normal:7-1'),('item:80209','normal:8-1')]:
            data['items'][ref]={'name':ref,'sources':[stage]}
            data['stages'][stage]={'cost':10,'drops':{ref:[{'chance':1,'amount':[1]}]}}
            snapshot['targets'].append(target(ref)); obs['stages'][stage]={'status':'sweepable'}
        for balance in (70,79):
            obs['balance']=balance
            self.assertEqual([r['count'] for r in plan(snapshot,obs,{},data=data)['rows']],[2,2,1,1,1])


class PriorityStorageTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.repo=ProfileRepository(Path(tmp.name)/'config/default'); self.repo.load_config()
        self.store=MaterialStore(self.repo)

    def test_old_definition_order_amount_versions_and_frozen_snapshot_survive(self):
        old={'revision':7,'targets':[dict(target(A),amount=20,priority=1),dict(target(B),amount=30,priority=2)]}
        for t in old['targets']: t.pop('stock_limit_enabled')
        atomic_json(self.store.path,old)
        frozen={'targets':deepcopy(old['targets']),'catalog_version':'old','rules':{}}
        state=self.store.state(); state['completed'][A+'@v1']={'at':1,'quantity':20}
        state['rounds']['old']={'snapshot':frozen,'used':{},'blocked':[],'receipts':[]}
        atomic_json(self.store.state_path,state)
        definitions=self.store.definitions()
        self.assertEqual([t['ref'] for t in definitions['targets']],[B,A])
        self.assertTrue(all(t['stock_limit_enabled'] for t in definitions['targets']))
        self.assertEqual(json.loads(self.store.path.read_text('utf-8')),old)
        self.store.save_targets(definitions['targets'],7)
        self.assertEqual(json.loads(self.store.path.with_name('material-goals.v1.backup.json').read_text('utf-8')),old)
        self.assertEqual(self.store.freeze('old'),frozen)
        self.assertEqual(self.store.state()['completed'],state['completed'])
        self.assertEqual(self.store.definitions()['targets'],definitions['targets'])
        self.store.save_targets(self.store.definitions()['targets'])
        self.assertEqual(json.loads(self.store.path.with_name('material-goals.v1.backup.json').read_text('utf-8')),old)

    def test_new_selection_needs_no_quantity_and_old_completion_cannot_stop_it(self):
        self.store.save_targets([{'ref':A,'amount':20}]); first=self.store.freeze('stock')
        self.store.observe({'inventory':{A:20},'source':'game','at':1},first)
        draft=self.store.definitions()['targets']; draft[0]['stock_limit_enabled']=False
        self.store.save_targets(draft)
        snapshot=self.store.freeze('weighted')
        self.assertEqual(len(self.store.remaining(snapshot)),1)
        self.assertFalse(self.store.needs_work('weighted'))
        draft[0]['stock_limit_enabled']=True; self.store.save_targets(draft)
        self.assertFalse(self.store.remaining(self.store.freeze('stock-again')))

    def test_quota_receipt_is_atomic_idempotent_and_not_a_goal_completion(self):
        self.store.save_targets([target(A)])
        snapshot=self.store.freeze('round')
        obs={'inventory':{},'balance':100,'source':'game','at':1,'stages':{S:{'status':'sweepable'}}}
        table=plan(snapshot,obs,{})
        self.store.save_allocation('round','step','front',table)
        batch=self.store.prepare_batch('round','front',S,5,[A],'step')
        self.store.result_seen(batch,5)
        self.assertTrue(self.store.settle(batch,obs)); self.assertFalse(self.store.settle(batch,obs))
        record=self.store.allocation('round','step')
        self.assertEqual((record['completed'],sum(r['count'] for r in record['rows'])),(5,5))
        self.assertFalse(self.store.state()['completed'])
        self.assertTrue(self.store.needs_work('round','step'))


class PriorityExecutionTests(TestCase):
    setUp = PriorityStorageTests.setUp
    def run_setup(self, shared=False, limited=False, multiple=False, rules=None):
        self.data,self.snapshot,self.observation=fixture(shared)
        if not shared and not multiple: self.snapshot['targets']=self.snapshot['targets'][:1]
        if limited: self.snapshot['targets'][0].update(stock_limit_enabled=True,amount=1)
        self.patches=[patch('core.material_planner.catalog',return_value=self.data),patch('module.material_sweep.catalog',return_value=self.data)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.store.save_targets(self.snapshot['targets'])
        if rules: self.store.set_adjustments('routine','front',rules)
        self.snapshot=self.store.freeze('round')
        self.worker=SimpleNamespace(current_instance_id='front',material_allocation_id='front-step',material_inventory_only=False,
            task_params={'material_sweep':{'reserve':0}},guard=Mock(),plan_pass=None,note=Mock(),click=Mock(),to_main_page=Mock())
        self.balance=100; self.stock=0; self.calls=[]
        self.observer=Mock()
        def observe(*_):
            return dict(deepcopy(self.observation),balance=self.balance,inventory={A:self.stock} if limited else {})
        self.observer.collect.side_effect=observe; self.observer.after_batch.side_effect=observe
        self.observer.select.return_value=True
        def start(w,count,cost,*,before_confirm):
            actual=min(count,self.balance//cost)
            if not actual: return sweep.SweepBatch()
            before_confirm(actual,self.balance-actual*cost)
            self.balance-=actual*cost; self.stock+=actual; self.calls.append(actual)
            return sweep.SweepBatch(actual,self.balance)
        self.start=start

    def run_step(self):
        with patch.object(sweep,'start_sweep',side_effect=self.start),patch.object(sweep,'return_to_list'):
            return execute(self.worker,self.store,'round',self.observer)

    def test_six_of_ten_retains_four_resume_does_not_reissue_and_tail_is_new(self):
        self.run_setup()
        normal=self.start
        def reduce(w,count,cost,**kwargs):
            self.balance=min(60,self.balance)
            return normal(w,count,cost,**kwargs)
        self.start=reduce; self.run_step()
        self.assertEqual(sum(self.calls),6)
        self.assertEqual(self.worker.note.call_args.kwargs['remaining'],[{'stage_id':S,'count':4}])
        self.balance=100; self.start=normal; self.run_step()
        self.assertEqual(sum(self.calls),10)
        self.assertFalse(self.store.needs_work('round','front-step'))
        self.run_step(); self.assertEqual(sum(self.calls),10)
        self.worker.current_instance_id='tail'; self.worker.material_allocation_id='tail-step'
        self.run_step(); self.assertEqual(sum(self.calls),16)

    def test_result_is_settled_before_post_batch_failure_and_never_replayed(self):
        self.run_setup()
        observe=self.observer.after_batch.side_effect
        self.observer.after_batch.side_effect=RuntimeError('读取中断')
        with self.assertRaisesRegex(RuntimeError,'读取中断'): self.run_step()
        self.assertEqual(self.calls,[5]); self.assertIsNone(self.store.state()['pending'])
        self.observer.after_batch.side_effect=observe; self.run_step()
        self.assertEqual(self.calls,[5,5]); self.assertEqual(self.store.allocation('round','front-step')['completed'],10)

    def test_unknown_consumption_blocks_new_key_and_keeps_quota_closed_after_review(self):
        self.run_setup(); normal=self.start
        def unknown(w,count,cost,**kwargs):
            normal(w,count,cost,**kwargs)
            raise RuntimeError('结果丢失')
        self.start=unknown
        with self.assertRaisesRegex(RuntimeError,'结果丢失'): self.run_step()
        self.worker.material_allocation_id='another-key'
        with self.assertRaisesRegex(RuntimeError,'待核对'): self.run_step()
        self.store.resolve_pending(True); self.start=normal; self.run_step()
        self.assertEqual(self.calls,[5])
        self.assertEqual(self.worker.note.call_args.kwargs['status'],'SKIPPED')
        self.assertFalse(self.store.needs_work('round','front-step'))

    def test_stock_stop_reallocates_only_unspent_budget_to_unlimited_material(self):
        self.run_setup(shared=True,limited=True)
        self.run_step()
        self.assertEqual(sum(self.calls),10)
        self.assertEqual(self.calls[0],1)
        self.assertIn(A+'@'+self.snapshot['targets'][0]['version'],self.store.state()['completed'])
        self.assertFalse(self.store.needs_work('round','front-step'))

    def test_observer_pure_counts_reads_no_stock_and_does_not_scan_all_sources(self):
        self.run_setup(shared=True)
        w=SimpleNamespace(config={'game':{'channel':'onestore'}},connection=Mock(),guard=Mock(),current_instance_id='front')
        w.connection.shell.return_value='versionName=test'
        observer=Observer(w); observer.select=Mock(return_value=True); observer.stock_on_stage=Mock()
        with patch.object(sweep,'list_balance',return_value=100):
            obs=observer.collect(self.snapshot)
            observer.after_batch(obs,S,sweep.SweepBatch(5,50))
        observer.stock_on_stage.assert_not_called()
        self.assertEqual(observer.select.call_count,2)

    def test_existing_frozen_inventory_round_still_uses_legacy_executor(self):
        self.run_setup(limited=True)
        state=self.store.state(); frozen=state['rounds']['round']['snapshot']
        frozen.pop('allocation_version')
        for t in frozen['targets']: t['priority']=1
        atomic_json(self.store.state_path,state)
        self.observer.after_batch.side_effect=RuntimeError('旧轮次读取中断')
        with self.assertRaisesRegex(RuntimeError,'旧轮次'): self.run_step()
        self.assertEqual(self.store.state()['pending']['phase'],'result_observed')
        self.assertFalse(self.store.state()['rounds']['round'].get('allocations'))

    def test_batches_do_not_restart_weighting_and_zero_quota_does_not_refill(self):
        self.run_setup(multiple=True); self.run_step()
        self.assertEqual(self.store.allocation('round','front-step')['by_stage'],{S:5,T:3,U:2})
        self.worker.material_allocation_id='empty'; self.run_step()
        self.assertEqual(self.worker.note.call_args.kwargs['status'],'SKIPPED')
        self.balance=100; self.run_step()
        self.assertEqual(sum(self.calls),10)

    def test_capped_shared_ref_is_not_credited_or_replenished_incidentally(self):
        self.run_setup(shared=True,rules={A:{'max_runs':0},C:{'max_runs':2}})
        self.run_step()
        used=self.store.state()['rounds']['round']['used']['front']
        self.assertEqual(sum(self.calls),10); self.assertNotIn(A,used); self.assertEqual(used[C],2)
        self.assertEqual(used[D],10)

    def test_unavailable_source_replans_unspent_debt_then_stops_if_none(self):
        self.run_setup()
        self.data['stages'][T]['drops'][A]=[{'chance':1,'amount':[1,0]}]
        self.data['items'][A]['sources'].append(T)
        def reject(stage): self.observation['stages'][stage]={'status':'unavailable'}
        self.observer.reject_stage.side_effect=reject
        self.observer.select.side_effect=lambda stage:stage!=S
        self.run_step()
        self.assertEqual(self.store.allocation('round','front-step')['by_stage'],{T:10})
        self.worker.material_allocation_id='unavailable'; self.balance=100
        self.observer.select.return_value=False; self.observer.select.side_effect=None
        self.run_step()
        self.assertEqual(sum(self.calls),10)
        self.assertTrue(self.store.needs_work('round','unavailable'))
        self.assertEqual(sum(r['count'] for r in self.store.allocation('round','unavailable')['rows']),10)

    def test_stock_read_error_is_local_and_incidental_stock_is_reread(self):
        self.run_setup(shared=True,limited=True)
        w=SimpleNamespace(config={'game':{'channel':'onestore'}},connection=Mock(),guard=Mock(),current_instance_id='front')
        w.connection.shell.return_value='versionName=test'
        observer=Observer(w); observer.select=Mock(return_value=True)
        observer.stock_on_stage=Mock(side_effect=RuntimeError('库存提示未出现'))
        with patch.object(sweep,'list_balance',return_value=100):
            obs=observer.collect(self.snapshot)
            self.assertIsNone(obs['inventory'][A]); self.assertNotIn(A,obs['inventory_at'])
            self.assertTrue(plan(self.snapshot,obs,{},data=self.data)['rows'])
            observer.stock_on_stage=Mock(return_value={A:50})
            obs['inventory'].clear()
            updated=observer.after_batch(obs,S,sweep.SweepBatch(1,90))
        observer.stock_on_stage.assert_called_once_with([A]); self.assertEqual(updated['inventory'][A],50)

    def test_unknown_stock_wait_resolves_without_new_unlimited_quota(self):
        self.run_setup(shared=True,limited=True)
        self.stock=None; self.start=lambda *_args,**_kwargs: None  # replace with stock-independent stub
        def start(w,count,cost,*,before_confirm):
            before_confirm(count,self.balance-count*cost); self.balance-=count*cost; self.calls.append(count)
            return sweep.SweepBatch(count,self.balance)
        self.start=start; self.run_step()
        self.assertEqual(sum(self.calls),10); self.assertTrue(self.store.needs_work('round','front-step'))
        self.stock=1; self.balance=100; self.run_step()
        self.assertEqual(sum(self.calls),10); self.assertFalse(self.store.needs_work('round','front-step'))

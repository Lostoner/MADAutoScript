"""Common MAD controls used by BAAS normal-task and scrimmage flows."""
from copy import deepcopy
from dataclasses import dataclass
import re
import cv2
from core.picture import co_detect
from core.image import swipe_search_target_str, screenshot_cut
from core.game_catalog import stage_options
from core.mad_features import FEATURES, SWEEP_POINTS, STAGE_ENTRIES, norm
from core.color import rgb_in_range

RESOURCE_AREAS={'normal_stage':(900,23,987,65),'flara_stage':(1041,28,1120,59),'procurement_stage':(1041,28,1120,59)}

def stage_text(text):
    return norm(text).upper()

def stage_text_area(self):
    # Normal-stage stars are detected as text and can flip BAAS OCR's shared
    # orientation vote by 180 degrees. Keep them outside the name search;
    # the separate pixel check below still verifies all three stars.
    return (305,82,510,697) if self.sweep_page=='normal_stage' else (305,82,610,697)

def selected(self):
    # BAAS normal-task search uses en-us; use it for the selected row too.
    language='en-us' if self.sweep_page=='normal_stage' else 'zh-cn'
    for row in self.scan(stage_text_area(self),language):
        x,y=row['point']
        if stage_text(row['text'])==self.sweep_target and x<510:
            # BAAS uses the selected-page colour feature as the loop end.
            # MAD highlights vary by category; unselected rows stay white.
            hsv=cv2.cvtColor(screenshot_cut(self,(310,max(82,y-20),500,min(697,y+20))),cv2.COLOR_BGR2HSV)
            return float(((hsv[:,:,1]>90)&(hsv[:,:,2]>85)).mean())>.3
    return False

FEATURES.update({
    'stage_selected':selected,
    'sweep_ready':lambda s:s.template('m4_sweep_button'),
    'normal_zone_readable':lambda s:bool(re.search(r'ZONE\s*\d+',s.line((127,514,249,557),'en-us','ZONE0123456789'))),
    'normal_zone':lambda s:bool(re.fullmatch(r'ZONE'+str(s.target_zone),s.line((127,514,249,557),'en-us','ZONE0123456789'))),
    'sweep_count_readable':lambda s:s.line((624,270,667,300),'en-us','0123456789').isdigit(),
    'stage_unavailable':lambda s:any(word in ''.join(r['text'] for r in s.scan((680,530,1200,700))) for word in ('未解锁','无法扫荡','三星通关','3星通关')),
})

def enter(self,page):
    self.update_screenshot_array()
    if self.match(page): return
    self.open_page('challenge')
    co_detect(self,img_ends=page,img_reactions={'challenge':STAGE_ENTRIES[page]})

def select_stage(self,task,stage_id):
    options=stage_options(task)
    option=options[stage_id]
    candidates=[stage_text(v['target']) for v in options.values() if v['group']==option['group']]
    self.sweep_target=stage_text(option['target'])
    point=swipe_search_target_str(self,search_area=stage_text_area(self),possible_strs=candidates,
        target_str_index=candidates.index(self.sweep_target),swipe_params=(512,606,512,234,.5,.6),
        ocr_language='en-us' if self.sweep_page=='normal_stage' else 'zh-cn',ocr_str_replace_func=stage_text)
    if point is None: raise RuntimeError('关卡列表未找到 '+option['title'])
    # BAAS check_sweep_availability equivalent: a dark star means not SSS.
    if any(rgb_in_range(self,x,point[1],20,100,20,110,20,150) for x in (523,551,580)):
        self.note(option['title']+' 未三星或未解锁，保留此关计划。')
        return False
    self.click(*point,wait_over=True,rate=2)
    co_detect(self,img_ends='stage_selected',img_reactions={self.sweep_page:point})
    # Availability follows the game's sweep-button state, as in BAAS check_sweep_availability.
    if not self.template('m4_sweep_button'):
        self.note(option['title']+' 当前不可扫荡，保留此关计划。')
        return False
    return True

@dataclass(frozen=True)
class SweepBatch:
    count: int = 0  # nonzero only after the game displays its result
    balance_after: int | None = None
    stage_limited: bool = False

def list_balance(self):
    value=self.line(RESOURCE_AREAS[self.sweep_page],'en-us','0123456789/')
    match=re.fullmatch(r'([0-9]+)/[1-9][0-9]*',value)
    return int(match[1]) if match else None

def preview_balance(self,count,cost):
    # Both the ordinary and academy dialogs show the balance before → after.
    # Use the projection only if it agrees with the game's selected count.
    before=self.line((499,354,593,389),'en-us','0123456789')
    after=self.line((686,354,778,389),'en-us','0123456789')
    if before.isdigit() and after.isdigit() and int(before)-int(after)==count*cost:
        return int(after)
    return None

def denied_batch(self,state):
    if state=='inadequate':
        rows=self.scan((280,120,1080,610))
        text=''.join(row['text'] for row in rows)
        local='次数不足' in text and not any(word in text for word in ('体力','能量','票券'))
        close=next((r['point'] for r in reversed(rows) if r['text'] in ('关闭','确定','确认')),None)
        if close and not any(word in text for word in ('购买','补充','消耗钻石')):
            self.click(*close,wait_over=True)
        return SweepBatch(stage_limited=local)
    return SweepBatch()

def start_sweep(self,count,cost,*,before_confirm=None):
    state=co_detect(self,img_ends=['sweep_confirm','inadequate','stamina_purchase'],img_reactions={self.sweep_page:SWEEP_POINTS['open']})
    if state!='sweep_confirm': return denied_batch(self,state)
    # Live calibration: MIN=1, MAX=available native count (23 at 230 stamina),
    # plus at MAX stays 23. There is no script-imposed ten-run batch cap.
    self.click(*SWEEP_POINTS['max'],wait_over=True)
    self.update_screenshot_array()
    co_detect(self,img_ends='sweep_count_readable',skip_first_screenshot=True)
    native_max=int(self.line((624,270,667,300),'en-us','0123456789'))
    desired=native_max if count=='max' else min(count,native_max)
    if desired<native_max:
        self.click(*SWEEP_POINTS['min'],wait_over=True)
        if desired>1: self.click(*SWEEP_POINTS['plus'],count=desired-1,duration=(desired-1)*.08,wait_over=True)
    self.update_screenshot_array()
    # MAD's native count control may clamp; read its final count, not resource deltas.
    co_detect(self,img_ends='sweep_count_readable',skip_first_screenshot=True)
    actual=int(self.line((624,270,667,300),'en-us','0123456789'))
    if actual>desired:
        self.click(*SWEEP_POINTS['cancel'])
        raise RuntimeError(f'扫荡确认次数 {actual} 超过本批计划 {desired}，已取消。')
    after=preview_balance(self,actual,cost)
    if not actual:
        self.click(*SWEEP_POINTS['cancel'])
        return SweepBatch(balance_after=after,stage_limited=after is not None and after>=cost)
    self.logger.info('扫荡 %s：计划 %s，本批 %s',self.sweep_target,count,actual)
    if before_confirm is not None:
        # Material tasks persist identity before the only irreversible click.
        # Send it once; a timeout must not cause an automatic second confirm.
        before_confirm(actual,after)
        self.click(*SWEEP_POINTS['confirm'])
        state=co_detect(self,img_ends=['sweep_result','inadequate','stamina_purchase'])
        return SweepBatch(actual,after) if state=='sweep_result' else denied_batch(self,state)
    state=co_detect(self,img_ends=['sweep_result','inadequate','stamina_purchase'],
        img_reactions={'sweep_confirm':SWEEP_POINTS['confirm']})
    return SweepBatch(actual,after) if state=='sweep_result' else denied_batch(self,state)

def return_to_list(self):
    co_detect(self,img_ends=self.sweep_page,img_reactions={'sweep_result':SWEEP_POINTS['result'],
        'sweep_confirm':SWEEP_POINTS['cancel'],'reward_popup':(640,592),'stamina_purchase':(1023,130)})

def run_plans(self,task,page,navigate):
    """Each instance owns its remaining plans; stage lookup still uses the task type."""
    config=self.repository.load_config()
    instance=getattr(self,'current_instance_id',None) or task
    plans=deepcopy(config['unfinished_tasks'].get(instance,[]))
    if not plans:
        params=getattr(self,'task_params',{}).get(task[4:],config['routine'][task[4:]])
        reason='本轮没有剩余关卡，本次跳过，未执行扫荡。' if params['plans'] else '未配置关卡，本次跳过，未执行扫荡。'
        self.note(reason,status='SKIPPED',completed=0,remaining=[]); return True
    self.sweep_page=page
    enter(self,page)
    completed=0
    reasons=[]
    options=stage_options(task)
    balance=list_balance(self)
    insufficient=False
    for plan in plans:
        stage_id,count=plan['stage_id'],plan['count']
        option=options[stage_id]
        cost=option['cost']
        if balance is not None and balance<cost:
            insufficient=True
            continue  # a cheaper remaining stage may still be affordable
        navigate(self,option)
        if not select_stage(self,task,stage_id):
            reasons.append(self.task_details.get('reason',option['title']+' 不可扫荡。'))
            continue
        remaining=count
        while remaining=='max' or remaining>0:
            if not self.template('m4_sweep_button'):
                reasons.append(option['title']+' 当前次数已用完，保留余项。')
                break
            batch=start_sweep(self,remaining,cost)
            actual=batch.count
            if not actual:
                if batch.stage_limited:
                    reasons.append(option['title']+' 当前可扫次数不足，保留此关计划。')
                    self.to_main_page()
                    enter(self,page)
                    balance=list_balance(self)
                    break
                self.note(f'本次扫荡 {completed} 次；游戏可扫荡次数为零或提示资源不足，保留未完成计划。',status='PARTIAL',completed=completed,
                    remaining=self.repository.load_config()['unfinished_tasks'].get(instance,[]))
                self.to_main_page(); return True
            # Save when result appears; unreadable/zero post-balance cannot undo completion.
            self.repository.complete_sweep(instance,stage_id,actual,finish_max=remaining=='max')
            completed+=actual
            return_to_list(self)
            balance=list_balance(self)
            if balance is None: balance=batch.balance_after
            if remaining=='max': break  # MAX consumes this stage's native allowance.
            remaining-=actual
            if remaining>0 and balance is not None and balance<cost:
                insufficient=True
                break
    if insufficient: reasons.append('当前体力或能量不足一场，保留未执行次数，继续后续指令。')
    pending=self.repository.load_config()['unfinished_tasks'].get(instance,[])
    message=f'本次扫荡 {completed} 次；'+('未完成关卡保留待续。' if pending else '所选关卡已完成。')
    self.note(message+''.join(reasons),status='PARTIAL' if pending else 'SUCCESS',completed=completed,remaining=pending)
    return True

"""Common MAD controls used by BAAS normal-task and scrimmage flows."""
from copy import deepcopy
from dataclasses import dataclass
import re
import cv2
from core.picture import co_detect
from core.exception import FunctionCallTimeout, SweepResultUncertain
from core.image import swipe_search_target_str, screenshot_cut
from core.game_catalog import HARD_DAILY_LIMIT, stage_options
from core.mad_features import FEATURES, SWEEP_POINTS, STAGE_ENTRIES, blue, norm
from core.color import rgb_in_range

RESOURCE_AREAS={'normal_stage':(900,23,987,65),'flara_stage':(1041,28,1120,59),'procurement_stage':(1041,28,1120,59)}
ZONE_AREA=(127,514,249,557)
HARD_DENIALS=('stamina_purchase','hard_attempt_dialog','inadequate')
DIALOG_AREA=(280,120,1080,610)

class HardScreenUnreadable(RuntimeError):
    """Cannot safely identify the current HARD screen or stage."""

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

def hard_attempt_dialog(self):
    # The row label "剩余进入次数" alone is not a reset offer.
    text=''.join(r['text'] for r in self.scan(DIALOG_AREA))
    return '次数' in text and any(w in text for w in ('购买','重置','补充','恢复次数','恢复挑战','追加'))

def notice_body(self):
    if self.line((607,270,674,302))=='通知' and self.line((607,408,674,444)) in ('确认','确定'):
        return self.line((416,326,865,365))
    return ''

def zone_locked_notice(self):
    body=notice_body(self)
    return '通关' in body and ('时开放' in body or '解锁' in body)

def hard_count_readable(self):
    # A count on a purchase/reset dialog must never enable the spending click.
    return (self.match('sweep_confirm') and self.match('sweep_count_readable') and
            bool(re.fullmatch(r'是否消耗体力(?:维他命)?(?:进行)?扫荡[？?]?',self.line((483,423,796,457)))))

FEATURES.update({
    'stage_selected':selected,
    'sweep_ready':lambda s:s.template('m4_sweep_button'),
    'normal_difficulty':lambda s:blue(s,(100,103,269,144))>.4,
    'hard_difficulty':lambda s:blue(s,(100,166,269,207))>.4,
    'normal_zone_readable':lambda s:bool(re.search(r'ZONE\s*\d+',s.line(ZONE_AREA,'en-us','ZONE0123456789'))),
    'normal_zone':lambda s:s.line(ZONE_AREA,'en-us','ZONE0123456789')=='ZONE'+str(s.target_zone),
    'zone_locked_notice':zone_locked_notice,
    'hard_attempt_dialog':hard_attempt_dialog,
    'sweep_count_readable':lambda s:s.line((624,270,667,300),'en-us','0123456789').isdigit(),
    'hard_count_readable':hard_count_readable,
    'stage_unavailable':lambda s:any(word in ''.join(r['text'] for r in s.scan((680,530,1200,700))) for word in ('未解锁','无法扫荡','三星通关','3星通关')),
})

def hard_wait(self,ends,message,*,time_out=15,**kwargs):
    # Only explicit reactions may click. In particular, never retry a network
    # or purchase confirmation while waiting for the result of a HARD sweep.
    try:
        return co_detect(self,img_ends=ends,time_out=time_out,handle_popups=False,**kwargs)
    except FunctionCallTimeout as exc:
        raise HardScreenUnreadable(message) from exc

def navigate_story(self,option,difficulty,*,check_locked=False):
    target=self.target_zone=option['zone']
    hard=difficulty=='hard'
    if hard:
        hard_wait(self,'hard_difficulty','未确认 HARD 页签已选中。',
                  img_reactions={'normal_stage':(185,187)},skip_first_screenshot=True)
        hard_wait(self,'normal_zone_readable','无法读取 HARD 区域。',skip_first_screenshot=True)
    else:
        co_detect(self,img_ends='normal_difficulty',img_reactions={'normal_stage':(185,124)},skip_first_screenshot=True)
        co_detect(self,img_ends='normal_zone_readable',skip_first_screenshot=True)
    # Each difficulty remembers its own zone. Never compute a direction before switching.
    text=self.line(ZONE_AREA,'en-us','ZONE0123456789')
    match=re.fullmatch(r'ZONE(\d+)',text) if hard else re.search(r'ZONE\s*(\d+)',text)
    if not match:
        raise (HardScreenUnreadable if hard else RuntimeError)('无法读取主线区域编号。')
    current=int(match[1])
    if not hard and not check_locked:
        if current!=target:
            co_detect(self,img_ends='normal_zone',img_reactions={'normal_stage':(263 if current<target else 103,534)})
        return  # original NORMAL contract
    while current!=target:
        expected=current+(1 if current<target else -1)
        self.click(263 if current<target else 103,534,wait_over=True,rate=3)
        if hard:
            self.target_zone=expected
            state=hard_wait(self,['normal_zone','zone_locked_notice'],f'无法确认 HARD 区域 {current} → {expected}。')
            if state=='zone_locked_notice':
                self.click(640,423,wait_over=True)  # verified unlock notice, not a purchase
                hard_wait(self,'normal_stage','关闭未解锁提示后未回到地区制霸。')
                self.note(option['title']+' 所在区域尚未解锁，保留此关计划。')
                return False
        else:
            self.update_screenshot_array()
            match=re.fullmatch(r'ZONE(\d+)',self.line(ZONE_AREA,'en-us','ZONE0123456789'))
            if not match or int(match[1])!=expected: return False
        current=expected
    return True

def enter(self,page):
    self.update_screenshot_array()
    if self.match(page): return
    self.open_page('challenge')
    co_detect(self,img_ends=page,img_reactions={'challenge':STAGE_ENTRIES[page]})

def hard_row_stars(self,y):
    # HARD prints the remaining-attempt banner below the name, so its stars
    # sit ten reference pixels below the title. Unknown colours are not a lock.
    xs=(523,551,580)
    if any(rgb_in_range(self,x,y+10,28,75,35,91,54,113) for x in xs): return False
    if all(rgb_in_range(self,x,y+10,205,255,135,235,5,145) for x in xs): return True
    raise HardScreenUnreadable('无法确认 '+self.sweep_target+' 的三星状态，未打开扫荡。')

def hard_row_limit(self,y):
    def allowance(value):
        match=re.fullmatch(r'(\d+)/(\d+)',norm(value))
        if not match: return None
        remaining,total=map(int,match.groups())
        if not 0<total or remaining>total: return None
        # Never grant extra attempts if an anomalous fraction reports a larger cap.
        return max(0,min(remaining,HARD_DAILY_LIMIT-(total-remaining)))

    # Associate the fraction with this row, never the next stage's allowance.
    for row in self.scan(stage_text_area(self),'en-us'):
        x,cy=row['point']
        if 420<=x<=485 and abs(cy-y-21)<=7:
            count=allowance(row['text'])
            if count is not None: return count
    count=allowance(self.line((425,y+10,477,y+32),'en-us','0123456789/'))
    if count is not None: return count
    raise HardScreenUnreadable('无法读取 '+self.sweep_target+' 的剩余进入次数，未打开扫荡。')

def select_stage(self,task,stage_id):
    """HARD returns the read allowance (including zero); False means unavailable."""
    options=stage_options(task)
    option=options[stage_id]
    candidates=[stage_text(v['target']) for v in options.values() if v['group']==option['group']]
    self.sweep_target=stage_text(option['target'])
    point=swipe_search_target_str(self,search_area=stage_text_area(self),possible_strs=candidates,
        target_str_index=candidates.index(self.sweep_target),swipe_params=(512,606,512,234,.5,.6),
        ocr_language='en-us' if self.sweep_page=='normal_stage' else 'zh-cn',ocr_str_replace_func=stage_text)
    hard=task=='mad.hard_sweep'
    if point is None:
        raise (HardScreenUnreadable if hard else RuntimeError)('关卡列表未找到 '+option['title'])
    if hard:
        if not self.match('hard_difficulty'): raise HardScreenUnreadable('未确认 HARD 页签，未选择关卡。')
        if not hard_row_stars(self,point[1]):
            self.note(option['title']+' 未三星，保留此关计划。')
            return False
        limit=hard_row_limit(self,point[1])
        if not limit:
            self.note(option['title']+' 本关剩余进入次数为零，继续下一关。')
            return 0
        self.click(*point,wait_over=True,rate=2)
        hard_wait(self,'stage_selected','未确认所选关卡为 '+option['title']+'，未打开扫荡。')
        if not self.template('m4_sweep_button'):
            if self.match('stage_unavailable'):
                self.note(option['title']+' 当前不可扫荡，保留此关计划。')
                return False
            raise HardScreenUnreadable('未辨认出 '+option['title']+' 的扫荡按钮。')
        return limit
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
        rows=self.scan(DIALOG_AREA)
        text=''.join(row['text'] for row in rows)
        local='次数不足' in text and not any(word in text for word in ('体力','能量','票券'))
        close=next((r['point'] for r in reversed(rows) if r['text'] in ('关闭','确定','确认')),None)
        if close and not any(word in text for word in ('购买','补充','消耗钻石')):
            self.click(*close,wait_over=True)
        return SweepBatch(stage_limited=local)
    return SweepBatch()

def hard_denied(self,state):
    local=False
    if state=='stamina_purchase':
        point=(1023,130)  # X on the stamina shop
    else:
        rows=self.scan(DIALOG_AREA)
        text=''.join(r['text'] for r in rows)
        local=state=='hard_attempt_dialog' or ('次数不足' in text and not any(w in text for w in ('体力不足','体力维他命不足')))
        point=next((r['point'] for r in reversed(rows) if r['text'] in ('取消','关闭','放弃') and r['point'][1]>300),None)
        # Only acknowledge an identified, single-purpose shortage notice. Unknown
        # offers stop here even if their only visible button is labelled "确认".
        if not point and state=='inadequate' and re.fullmatch(r'(?:剩余)?(?:进入次数|挑战次数|扫荡次数|次数|体力(?:维他命)?)不足[。！!]?',notice_body(self)):
            point=(640,423)
        if not point: raise RuntimeError('游戏提示限次或资源不足，未找到安全的退出按钮；未购买或重置。')
    self.click(*point,wait_over=True)
    hard_wait(self,self.sweep_page,'退出提示后未回到 HARD 关卡列表。',
              img_reactions={'sweep_confirm':SWEEP_POINTS['cancel']})
    return SweepBatch(stage_limited=local)

def dialog_count(self,hard):
    self.update_screenshot_array()
    if hard:
        state=hard_wait(self,[*HARD_DENIALS,'hard_count_readable'],'未能确认 HARD 体力扫荡页及次数，未确认消费。',skip_first_screenshot=True)
        if state!='hard_count_readable': return hard_denied(self,state)
    else: co_detect(self,img_ends='sweep_count_readable',skip_first_screenshot=True)
    return int(self.line((624,270,667,300),'en-us','0123456789'))

def start_sweep(self,count,cost,*,before_confirm=None,hard_limit=None):
    hard=hard_limit is not None
    if hard:
        hard_limit=min(hard_limit,HARD_DAILY_LIMIT)
        if hard_limit<=0: return SweepBatch(stage_limited=True)
        self.click(*SWEEP_POINTS['open'],wait_over=True)
        state=hard_wait(self,[*HARD_DENIALS,'sweep_confirm'],'未辨认出 HARD 扫荡确认页，未确认消费。')
        if state!='sweep_confirm': return hard_denied(self,state)
    else:
        state=co_detect(self,img_ends=['sweep_confirm','inadequate','stamina_purchase'],img_reactions={self.sweep_page:SWEEP_POINTS['open']})
        if state!='sweep_confirm': return denied_batch(self,state)
    # Live calibration: MIN=1, MAX=available native count (23 at 230 stamina),
    # plus at MAX stays 23. There is no script-imposed ten-run batch cap.
    self.click(*SWEEP_POINTS['max'],wait_over=True)
    native_max=dialog_count(self,hard)
    if isinstance(native_max,SweepBatch): return native_max  # MAX opened a resource/attempt offer
    desired=native_max if count=='max' else min(count,native_max)
    if hard: desired=min(desired,hard_limit)
    if desired<native_max:
        self.click(*SWEEP_POINTS['min'],wait_over=True)
        if desired>1: self.click(*SWEEP_POINTS['plus'],count=desired-1,duration=(desired-1)*.08,wait_over=True)
    # MAD's native count control may clamp; read its final count, not resource deltas.
    actual=dialog_count(self,hard)
    if isinstance(actual,SweepBatch): return actual
    if actual>desired or (hard and 0<actual<desired):
        self.click(*SWEEP_POINTS['cancel'])
        raise RuntimeError(f'扫荡确认次数 {actual} 与本批计划 {desired} 不符，已取消。')
    after=preview_balance(self,actual,cost)
    if not actual:
        self.click(*SWEEP_POINTS['cancel'])
        if hard:
            hard_wait(self,self.sweep_page,'取消零次扫荡后未回到关卡列表。')
            return SweepBatch(balance_after=after,stage_limited=after is None or after>=cost)
        return SweepBatch(balance_after=after,stage_limited=after is not None and after>=cost)
    self.logger.info('扫荡 %s：计划 %s，本批 %s',self.sweep_target,count,actual)
    if before_confirm is not None or hard:
        if before_confirm is not None: before_confirm(actual,after)
        try:
            self.click(*SWEEP_POINTS['confirm'])  # exactly once, outside every reaction loop
            state=(hard_wait(self,['sweep_result',*HARD_DENIALS],'未看到扫荡结算。',time_out=45) if hard else
                   co_detect(self,img_ends=['sweep_result','inadequate','stamina_purchase']))
        except Exception as exc:
            if not hard: raise
            raise SweepResultUncertain(f'{self.sweep_target} ×{actual} 已尝试确认，结算不明。请先核对游戏内剩余次数再继续；本批未记账、不会自动重试。') from exc
        if state=='sweep_result': return SweepBatch(actual,after)
        return hard_denied(self,state) if hard else denied_batch(self,state)
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
    hard=task=='mad.hard_sweep'
    balance=list_balance(self)
    insufficient=False
    for plan in plans:
        stage_id,count=plan['stage_id'],plan['count']
        option=options[stage_id]
        cost=option['cost']
        if balance is not None and balance<cost:
            insufficient=True
            continue  # a cheaper remaining stage may still be affordable
        availability=False if navigate(self,option) is False else select_stage(self,task,stage_id)
        if not availability:
            reasons.append(self.task_details.get('reason',option['title']+' 不可扫荡。'))
            continue
        remaining=count
        while remaining=='max' or remaining>0:
            if not hard and not self.template('m4_sweep_button'):
                reasons.append(option['title']+' 当前次数已用完，保留余项。')
                break
            batch=(start_sweep(self,remaining,cost,hard_limit=availability) if hard else
                   start_sweep(self,remaining,cost))
            actual=batch.count
            if not actual:
                if batch.stage_limited:
                    reasons.append(option['title']+' 当前可扫次数不足，保留此关计划。')
                    if not hard:
                        self.to_main_page()
                        enter(self,page)
                    balance=list_balance(self)
                    break
                self.note(f'本次扫荡 {completed} 次；游戏可扫荡次数为零或提示资源不足，保留未完成计划。',status='PARTIAL',completed=completed,
                    remaining=self.repository.load_config()['unfinished_tasks'].get(instance,[]))
                self.to_main_page(); return True
            # Save when result appears; unreadable/zero post-balance cannot undo completion.
            try:
                self.repository.complete_sweep(instance,stage_id,actual,finish_max=remaining=='max')
            except OSError as exc:
                if not hard: raise
                raise SweepResultUncertain(f'{option["title"]} 已结算 {actual} 次，但进度未能保存；请先核对再继续。') from exc
            completed+=actual
            return_to_list(self)
            balance=list_balance(self)
            if balance is None: balance=batch.balance_after
            if remaining=='max': break  # MAX consumes this stage's native allowance.
            remaining-=actual
            if remaining>0 and balance is not None and balance<cost:
                insufficient=True
                break
            if hard and remaining>0:
                # This batch already used the native cap. Do not reopen a depleted
                # stage (which may now offer a paid reset); later stages have their own cap.
                reasons.append(option['title']+f' 本批可扫 {actual} 次，还剩 {remaining} 次。')
                break
    if insufficient: reasons.append('当前体力或能量不足一场，保留未执行次数，继续后续指令。')
    pending=self.repository.load_config()['unfinished_tasks'].get(instance,[])
    message=f'本次扫荡 {completed} 次；'+('未完成关卡保留待续。' if pending else '所选关卡已完成。')
    self.note(message+''.join(reasons),status='PARTIAL' if pending else 'SUCCESS',completed=completed,remaining=pending)
    return True

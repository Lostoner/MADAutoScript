"""BAAS collect_daily_task_power: claim button, then each cumulative reward."""
from core.picture import co_detect
from core.mad_features import FEATURES,button
BOX_X=(557,708,860,1012,1163)
FEATURES['tasks_active']=lambda s:s.match('tasks') and button(s,(1036,656,1197,698),'全部领取')
FEATURES['tasks_inactive']=lambda s:s.match('tasks') and s.template('daily_claim_inactive')
FEATURES['point_active']=lambda s:s.match('daily_page') and button(s,(s.point_x-24,130,s.point_x+24,152),'领取')
FEATURES['point_done']=lambda s:s.match('daily_page') and not s.match('point_active')

def collect_all(self):
    if self.match('tasks_active'):
        co_detect(self,img_ends='tasks_inactive',img_reactions={'tasks_active':(1116,677),'reward_popup':(640,592)})
        return True
    return False

def implement(self):
    self.open_page('tasks')
    co_detect(self,img_ends='daily_page',img_reactions={'tasks':(145,112)},skip_first_screenshot=True)
    claimed=collect_all(self)
    boxes=[]
    for index,x in enumerate(BOX_X,1):
        self.point_x=x
        self._cache={}
        if not self.match('point_active'): continue
        co_detect(self,img_ends='point_done',img_reactions={'point_active':(x,141),'reward_popup':(640,592)})
        boxes.append(index)
    self.note('每日任务与积分宝箱已检查。',daily_claimed=claimed,boxes=boxes)
    return True

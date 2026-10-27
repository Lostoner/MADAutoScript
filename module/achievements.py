"""BAAS daily reward loop for MAD account/development achievement tabs."""
from core.picture import co_detect
from core.mad_features import FEATURES,blue,red
from module.daily_rewards import collect_all
FEATURES['achievement_category']=lambda s:s.match('achievement_page') and blue(s,(s.achievement_x-48,94,s.achievement_x+47,122))>.4

def implement(self):
    self.open_page('tasks')
    if not red(self,(216,144,237,166)):
        self.note('成就没有领奖红点。'); return True
    co_detect(self,img_ends='achievement_page',img_reactions={'tasks':(145,172)})
    claimed=[]
    for name,x in (('账号',308),('养成',427)):
        if not red(self,(x+39,89,x+59,108)): continue
        self.achievement_x=x
        self._cache={}
        co_detect(self,img_ends='achievement_category',img_reactions={'achievement_page':(x,110)},skip_first_screenshot=True)
        if collect_all(self): claimed.append(name)
    self.note('成就领奖已检查。',achievement_claimed=claimed)
    return True

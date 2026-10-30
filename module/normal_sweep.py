"""BAAS explore_tasks.sweep_task.sweep_normal_task, MAD normal stages."""
import re
from core.picture import co_detect
from core.mad_features import FEATURES, blue
from module.sweep_utils import run_plans

FEATURES['normal_difficulty']=lambda s:blue(s,(100,103,269,144))>.4

def navigate(self,option):
    self.target_zone=option['zone']
    # The game remembers HARD independently of the area number. Select NORMAL
    # before reading the zone, because changing difficulty can change that too.
    co_detect(self,img_ends='normal_difficulty',img_reactions={'normal_stage':(185,124)},skip_first_screenshot=True)
    co_detect(self,img_ends='normal_zone_readable',skip_first_screenshot=True)
    current=int(re.search(r'\d+',self.line((127,514,249,557),'en-us','ZONE0123456789')).group())
    if current!=self.target_zone:
        co_detect(self,img_ends='normal_zone',img_reactions={'normal_stage':(263 if current<self.target_zone else 103,534)})

def implement(self):
    return run_plans(self,'mad.normal_sweep','normal_stage',navigate)

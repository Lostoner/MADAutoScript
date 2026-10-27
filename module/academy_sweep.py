"""One BAAS scrimmage flow for Flara and procurement; only entry/data differ."""
from core.picture import co_detect
from core.mad_features import FEATURES,blue
from module.sweep_utils import run_plans

def category_selected(self):
    y=self.category_y
    return blue(self,(80,y-20,225,y+20))>.35
FEATURES['academy_category']=category_selected

def navigate(self,option):
    self.category_y=option['category_y']
    co_detect(self,img_ends='academy_category',img_reactions={self.sweep_page:(155,self.category_y)},skip_first_screenshot=True)

def implement(self,task,page):
    return run_plans(self,task,page,navigate)

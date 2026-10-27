"""BAAS collect_daily_free_power/shop_utils with MAD free-product labels."""
import re
from core.picture import co_detect
from core.mad_features import FEATURES,blue,norm

PERIODS={'daily':'每日','weekly':'每周','monthly':'每月'}
def menu_item(self,name):
    return next((r for r in self.scan((118,130,283,698)) if r['text']==name),None)
def selected(self):
    row=menu_item(self,self.mall_period)
    return self.match('mall') and row and blue(self,(130,row['point'][1]-13,267,row['point'][1]+13))>.3
FEATURES['mall_period']=selected

def implement(self):
    self.open_page('mall')
    claimed=[]
    for period in self.task_params['claim_all']['mall_periods']:
        title=PERIODS[period]
        option=menu_item(self,title)
        if option is None:
            ordinary=menu_item(self,'普通商品')
            if ordinary: self.click(*ordinary['point'],wait_over=True,rate=2); self.update_screenshot_array()
            option=menu_item(self,title)
        if option is None: raise RuntimeError('商城菜单未找到 '+title)
        self.mall_period=title; self._cache={}
        co_detect(self,img_ends='mall_period',img_reactions={'mall':option['point']},skip_first_screenshot=True)
        seen=set(); settled=set()
        while self.flag_run:
            rows=self.scan((337,130,1200,669))
            target=None
            for row in rows:
                x,y=row['point']
                if row['text'] not in ('免费','0') or x<430 or blue(self,(x-80,y-10,min(1200,x+80),min(669,y+10)))<.4: continue
                above=[r for r in rows if abs(r['point'][0]-x)<65 and 15<y-r['point'][1]<80
                       and not re.search(r'限购|剩余|购买.*次',r['text'])]
                if not above: continue
                name=min(above,key=lambda r:y-r['point'][1])['text']
                if name in settled: continue
                if any(norm(r['text']).upper()=='SOLDOUT' and abs(r['point'][0]-x)<85 and 40<y-r['point'][1]<220 for r in rows): continue
                target=(name,(x,y)); break
            if target:
                name,point=target
                state=co_detect(self,img_ends=['free_purchase','product_dialog'],img_reactions={'mall':point})
                if state=='free_purchase':
                    co_detect(self,img_ends='reward_popup',img_reactions={'free_purchase':(776,516)})
                    claimed.append(title+'：'+name)
                    co_detect(self,img_ends='mall',img_reactions={'reward_popup':(640,592)})
                else:
                    co_detect(self,img_ends='mall',img_reactions={'product_dialog':(504,516)})
                settled.add(name)
                continue
            signature=tuple(r['text'] for r in rows)
            if signature in seen: break
            seen.add(signature)
            self.swipe(1164,605,1164,230,.5,.6)
            co_detect(self,img_ends='mall')
    self.note('商城免费物品已检查。',mall_claimed=claimed)
    return True

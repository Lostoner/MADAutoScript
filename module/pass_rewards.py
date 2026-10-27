"""BAAS collect_pass_reward: tasks first, then available reward cards."""
import re
import cv2
import numpy as np
from core.picture import co_detect
from core.image import screenshot_cut
from core.mad_features import FEATURES,PASS_PERIODS,blue,red,red_positions

def yellow(self,area):
    hsv=cv2.cvtColor(screenshot_cut(self,area),cv2.COLOR_BGR2HSV)
    return float(np.mean(cv2.inRange(hsv,(15,100,140),(45,255,255))>0))>.4

FEATURES['pass_period']=lambda s:s.match('pass_missions') and yellow(s,(315,s.pass_period_y-13,408,s.pass_period_y+13))
FEATURES['pass_mission_done']=lambda s:s.match('pass_missions') and not any(abs(r['point'][0]-s.pass_claim_x)<40 and r['text']=='领取' for r in s.scan((427,535,1188,608)))

def screen(self,kind,mode='rewards'):
    co_detect(self,img_ends='pass_'+kind,img_reactions={'pass':(150,150 if kind=='monthly' else 232)},skip_first_screenshot=True)
    if kind=='monthly': co_detect(self,img_ends='pass_'+mode,img_reactions={'pass':(1131 if mode=='missions' else 1023,249)})

def swipe(self,left=True):
    # x>1075 is MAD's pinned milestone card, not the scrolling reward track.
    self.swipe(*( (1020,435,460,435) if left else (460,435,1020,435)),.5,1.2)
    co_detect(self,img_ends='pass')

def signature(self,missions=False):
    area=(427,350,1188,520) if missions else (420,276,1188,319)
    return tuple(r['text'] for r in self.scan(area))

def to_start(self,missions=False):
    previous=None
    while self.flag_run:
        current=signature(self,missions)
        if current==previous: return
        previous=current
        swipe(self,False)

def missions(self):
    screen(self,'monthly','missions')
    total=0
    for title,y in PASS_PERIODS:
        if not red(self,(399,y-23,417,y-6)): continue
        self.pass_period_y=y; self._cache={}
        co_detect(self,img_ends='pass_period',img_reactions={'pass_missions':(362,y)},skip_first_screenshot=True)
        to_start(self,True)
        seen=set()
        while self.flag_run:
            buttons=[r for r in self.scan((427,535,1188,608)) if r['text']=='领取' and 430<r['point'][0]<1180 and blue(self,(r['point'][0]-48,r['point'][1]-13,r['point'][0]+48,r['point'][1]+13))>.4]
            if buttons:
                point=buttons[0]['point']
                self.pass_claim_x=point[0]; self._cache={}
                co_detect(self,img_ends='pass_mission_done',img_reactions={'pass_missions':point,'reward_popup':(640,592)},skip_first_screenshot=True)
                total+=1; continue
            current=signature(self,True)
            if current in seen: break
            seen.add(current)
            if not red(self,(399,y-23,417,y-6)): break
            swipe(self)
    return total

def cards(self):
    """Only the badge at a card's top-right marks availability, not item artwork."""
    result=[]
    for kind,y in (('free',366),('premium',512)):
        for x,_ in red_positions(self,(427,y-43,1188,y-24)):
            if x-36<427: continue  # only a fully visible card can be clicked
            result.append({'row':kind,'available':True,'point':(x-36,y)})
    return result

def rewards(self,kind):
    screen(self,kind)
    to_start(self)
    seen=set(); claimed=[]
    while self.flag_run:
        available=[c for c in cards(self) if c['available']]
        if available:
            card=available[0]
            co_detect(self,img_ends='reward_popup',img_reactions={'pass_rewards':card['point']})
            self.save_screenshot('pass-'+kind+'-reward')
            co_detect(self,img_ends='pass_rewards',img_reactions={'reward_popup':(640,592)})
            claimed.append(card['row']); continue
        current=signature(self)
        if current in seen: break
        seen.add(current); swipe(self)
    return claimed

def implement(self):
    self.open_page('pass')
    mission_claims=missions(self)
    reward_claims={}
    for kind in ('monthly','level'):
        area=(250,108,287,134) if kind=='monthly' else (250,190,287,216)
        if red(self,area): reward_claims[kind]=rewards(self,kind)
    self.note('通行证任务和奖励已检查。',pass_missions=mission_claims,pass_rewards=reward_claims)
    return True

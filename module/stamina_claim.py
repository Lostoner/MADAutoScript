"""BAAS cafe_reward.collect_reward adapted to MAD accumulated stamina."""
from core.picture import co_detect
from core.mad_features import FEATURES, button

FEATURES['stamina_available']=lambda s:s.match('stamina_claim') and button(s,(719,552,781,588),'收取')
FEATURES['stamina_empty']=lambda s:s.match('stamina_claim') and not button(s,(719,552,781,588),'收取')

def implement(self):
    self.to_main_page()
    co_detect(self,img_ends='stamina_claim',img_reactions={'home':(780,41),'stamina_purchase':(344,276)})
    self.click(980,491,wait_over=True,rate=2)
    self.update_screenshot_array()
    if self.match('stamina_available'):
        co_detect(self,img_ends=['reward_popup','stamina_empty'],img_reactions={'stamina_available':(750,570)})
        self.note('累积体力已收取。')
    else: self.note('暂无累积体力可收取。')
    self.to_main_page()
    return True

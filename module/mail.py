"""BAAS mail.implement: active claim / reward / inactive; unknown logs and ends."""
from core.picture import co_detect
from core.mad_features import FEATURES,button
FEATURES['mail_active']=lambda s:s.match('mail') and (s.template('mail_claim_active') or button(s,(1034,641,1185,677),'一键领取'))
FEATURES['mail_inactive']=lambda s:s.match('mail') and s.template('mail_claim_inactive')

def implement(self):
    self.open_page('mail')
    if self.match('mail_active'):
        co_detect(self,img_ends='mail_inactive',img_reactions={'mail_active':(1110,659),'reward_popup':(640,592)})
        self.note('邮箱奖励已领取。')
    else: self.note('邮箱无可领取奖励，或领取按钮未匹配。')
    return True

"""BAAS collect_reward composition, preserving selected MAD child functions."""
from core.tasks import CLAIM_MODULES

def implement(self):
    from module import pass_rewards,mall,daily_rewards,achievements,mail
    params=self.task_params['claim_all']
    def tasks():
        return daily_rewards.implement(self) and achievements.implement(self)
    handlers={'pass':lambda:pass_rewards.implement(self),'mall':lambda:mall.implement(self),
              'tasks':tasks,'mail':lambda:mail.implement(self)}
    results=[]
    for name,handler in handlers.items():
        if not params['modules'].get(name): continue
        self.emit('reward_component','一键领取：'+CLAIM_MODULES[name],component=name)
        if not handler(): return False
        results.append({'component':name,'reason':self.task_details.get('reason','完成')})
    self.note('所选领取子功能已处理。',components=results)
    return True

"""BAAS restart/to_main_page and popup reactions with MAD visual data."""
import time
from core import picture
from core.mad_features import HOME_ENTRIES, STAGE_ENTRIES
from core.exception import GameDayChanged

def implement(self):
    if self.connection.get_current_package()!=self.package_name:
        self.connection.start_game()
    self.to_main_page()
    return True

def to_main_page(self,skip_first_screenshot=False):
    reactions={name:(1180,43) for name in ('mail','tasks','challenge','normal_stage','flara_stage','procurement_stage','normal_shop','pass')}
    reactions.update({'mall':(1194,39),'reward_popup':(640,592),'sweep_result':(640,575),
        'sweep_confirm':(496,501),'stamina_dialog':(1023,130),'gold_purchase':(525,575),
        'product_dialog':(504,516),'date_result':(1176,40),'date_confirm':(713,538),
        'date_map':(62,42),'date_plan':(62,42),'mochi_chat':(1178,41),'mochi_contacts':(1178,41)})
    result=picture.co_detect(self,img_ends='home',img_reactions=reactions,
        skip_first_screenshot=skip_first_screenshot,tentative_click=True,tentative_x=1180,tentative_y=43)
    self.date_popup_handled=False
    return result

def open_page(self,name):
    self.update_screenshot_array()
    if self.match(name): return name
    self.to_main_page(True)
    return picture.co_detect(self,img_ends=name,img_reactions={'home':HOME_ENTRIES[name]},skip_first_screenshot=True)

def deal_with_popup(self):
    # BAAS common rewards first; other dialogs are only searched after no task
    # end/reaction matched, not before every input.
    if self.match('reward_popup'):
        self.click(640,592); return True
    rows=self.scan((55,60,1225,700))
    text=''.join(r['text'] for r in rows)
    if '公告事项' in text:
        close=next((r['point'] for r in rows if r['text'] in ('X','×','x') and r['point'][0]>950 and r['point'][1]<180),None)
        if close: self.click(*close); return True
    if any(w in text for w in ('日期变更','日期已变更','日期发生变更','日期已更改','日期已经变更','每日重置')):
        first_seen=not self.date_popup_handled
        self.date_popup_handled=True
        confirm=next((r['point'] for r in rows if r['text'] in ('确认','确定','重新登录','重新开始') and r['point'][1]>300),None)
        if confirm: self.click(*confirm)
        else:
            self.connection.close_current_app(); self.connection.start_game()
        # Unwind the old plan before refreshing. solve resumes from saved
        # progress after login; a repeated dialog cannot clear it again.
        if first_seen: raise GameDayChanged()
        return True
    if 'TOUCHTOSTART' in text.upper() or '点击屏幕开始' in text or '点击开始' in text:
        self.click(640,590); return True
    names=None
    if any(w in text for w in ('连接服务器失败','网络连接失败','连接已断开','网络不稳定','服务器连接中断')):
        names=('重试','重新连接','确认','确定')
    elif any(w in text for w in ('每日签到','连续签到','签到奖励','公告')):
        names=('领取','收取','确认','确定','关闭','跳过')
    elif any(w in text for w in ('等级提升','等级上升','羁绊等级提升')):
        names=('确认','确定','关闭')
    if names:
        target=next((r['point'] for r in reversed(rows) if r['text'] in names and r['point'][1]>300),None)
        if target: self.click(*target); return True
    return False

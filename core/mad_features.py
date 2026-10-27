"""MAD image/colour/text feature data for BAAS ends and reactions.

Only requested features are evaluated on the current cached frame. Coordinates
are 1280x720; no whole-scene classifier or confidence-based input permission.
"""
import re
import cv2
import numpy as np
from core.image import screenshot_cut
from core.game_catalog import SHOP_ITEMS

HEADERS={'challenge':'挑战','normal_stage':'地区制霸','flara_stage':'弗拉瑞区域',
         'procurement_stage':'特别采购','normal_shop':'商店','mall':'阿米商城',
         'pass':'通行证','tasks':'任务','mail':'邮箱'}
HOME_ENTRIES={'challenge':(1105,626),'normal_shop':(370,650),'mall':(347,141),
              'pass':(184,137),'mail':(1007,40),'tasks':(197,650),'mochi':(265,140)}
STAGE_ENTRIES={'normal_stage':(865,264),'procurement_stage':(1080,488),'flara_stage':(1080,582)}
SWEEP_POINTS={'min':(432,284),'minus':(521,284),'plus':(766,284),'max':(856,284),
              'confirm':(784,501),'cancel':(496,501),'result':(640,575),'open':(766,657)}
PASS_PERIODS=(('每日',344),('第1周',384),('第2周',425),('第3周',467),('第4周',507))
MAP_LOCATIONS={'四君子':{'渡口':(179,202,233,234),'天灯街':(404,320,469,356),
    '华西园':(668,410,738,444),'和平楼':(204,495,277,530),'雪海温泉':(914,233,999,266)},
    '赫玛尼塔斯':{'DD镇':(266,266,321,300),'豆腐街':(125,433,193,471),
    '甜甜圈屋':(670,342,751,378),'繁华街':(1020,338,1095,379),'湖水公园':(1079,481,1157,525)},
    '贝尔蒙特':{'宴会厅':(283,224,349,254),'菲尔哈莫尼修道院':(861,198,1013,229),
    '贝尔蒙特广场':(558,363,679,391),'血腥玛丽':(163,442,247,467),'咖啡街':(763,534,831,562)}}

def norm(text): return re.sub(r'\s+','',text).replace('（','(').replace('）',')')
def centre(area): return ((area[0]+area[2])/2,(area[1]+area[3])/2)
def blue(self,area):
    hsv=cv2.cvtColor(screenshot_cut(self,area),cv2.COLOR_BGR2HSV)
    return float(np.mean(cv2.inRange(hsv,(90,90,85),(120,255,255))>0))
def red(self,area):
    return bool(red_positions(self,area))

def red_positions(self,area):
    hsv=cv2.cvtColor(screenshot_cut(self,area),cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,0]<10)|(hsv[:,:,0]>170))&(hsv[:,:,1]>150)&(hsv[:,:,2]>150)
    _,_,stats,centres=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    return [(area[0]+cx/self.ratio,area[1]+cy/self.ratio)
        for (x,y,w,h,a),(cx,cy) in zip(stats[1:],centres[1:])
        if a>=20 and min(w,h)>=6 and .6<=w/h<=1.5 and a/(w*h)>.55]
def button(self,area,text):
    return self.line(area)==text and blue(self,area)>.4
def header_clear(self):
    return self.template('common_home') or self.template('m4_mall_home') or self.template('pass_home')
def page(self,name):
    if not header_clear(self): return False
    if name=='procurement_stage' and self.template('m4_procurement_title'): return True
    if name=='normal_shop' and self.template('m4_normal_shop_title'): return True
    return self.line((125,16,308,68))==HEADERS[name]
def mochi(self): return self.template('m4_mochi_close') or self.template('m4_mochi_close_core')
def contacts(self): return mochi(self) and self.line((255,105,380,130))=='每日可约会次数'
def detail(self): return contacts(self) and bool(self.line((790,194,990,232)))
def pass_kind(self):
    title=self.line((299,87,676,140))
    return 'monthly' if '月度支援通行证' in title else 'level' if '升级支援通行证' in title else None

FEATURES={
    'home':lambda s:s.template('home_mail') and s.template('home_tasks'),
    'reward_popup':lambda s:s.template('popup_reward'),
    'sweep_confirm':lambda s:s.line((579,188,707,222))=='扫荡确认',
    'sweep_result':lambda s:s.line((583,117,699,149))=='扫荡结果',
    'stamina_dialog':lambda s:s.line((585,118,694,149))=='体力维他命',
    'stamina_claim':lambda s:s.match('stamina_dialog') and blue(s,(253,247,437,303))>.4,
    'stamina_purchase':lambda s:s.match('stamina_dialog') and blue(s,(253,170,437,228))>.4,
    'gold_purchase':lambda s:s.line((610,122,674,151))=='购买' and norm(s.line((479,169,680,195))) in {norm(p['title']) for p in SHOP_ITEMS.values()},
    'free_purchase':lambda s:s.line((590,140,690,170))=='出售商品' and s.line((490,242,575,280)) in ('免费','0'),
    'product_dialog':lambda s:s.line((590,140,690,170))=='出售商品',
    'mochi_chat':lambda s:mochi(s) and s.line((207,107,263,139))=='聊天',
    'mochi_contacts':contacts,'mochi_detail':detail,
    'date_map':lambda s:s.line((520,68,676,101))=='请选择约会路线。',
    'date_plan':lambda s:s.line((325,68,470,101))=='请选择约会路线。',
    'date_confirm':lambda s:s.line((612,150,667,182))=='约会' and s.template('m4_date_ticket'),
    'date_result':lambda s:s.template('m4_date_result_close') and (s.template('m4_date_gauge') or s.template('m4_date_rankup')),
    'daily_page':lambda s:page(s,'tasks') and blue(s,(79,92,222,137))>.4,
    'achievement_page':lambda s:page(s,'tasks') and blue(s,(79,151,222,192))>.4,
    'pass_monthly':lambda s:page(s,'pass') and pass_kind(s)=='monthly',
    'pass_level':lambda s:page(s,'pass') and pass_kind(s)=='level',
    'pass_missions':lambda s:page(s,'pass') and pass_kind(s)=='monthly' and blue(s,(1083,233,1184,263))>.5,
    'pass_rewards':lambda s:page(s,'pass') and (pass_kind(s)=='level' or blue(s,(973,233,1072,263))>.5),
}
for name in HEADERS: FEATURES[name]=lambda s,name=name:page(s,name)

def inadequate(self):
    text=''.join(r['text'] for r in self.scan((280,120,1080,610)))
    return any(x in text for x in ('体力维他命不足','能量维他命不足','票券不足','次数不足','金币不足','没有可使用的票券'))
FEATURES['inadequate']=inadequate

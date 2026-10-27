"""BAAS cafe named invitation + lesson tickets/location priority, MAD data."""
from core.picture import co_detect
from core.mad_features import FEATURES, MAP_LOCATIONS, norm, blue, centre

FEATURES['date_character']=lambda s:s.match('mochi_detail') and norm(s.line((790,194,990,232)))==s.date_character
FEATURES['date_location_selected']=lambda s:s.match('date_map') and blue(s,s.date_location_area)>.45

def contacts(self):
    self.update_screenshot_array()
    if not self.match('mochi_contacts'):
        self.to_main_page(True)
        co_detect(self,img_ends='mochi_contacts',img_reactions={'home':(265,140),'mochi_chat':(145,149)})

def select_character(self,target):
    """Cafe invite list: traverse to start, then until the last item repeats."""
    self.date_character=norm(target)
    if self.match('date_character'): return True
    for direction in (-1,1):
        previous=None
        while self.flag_run:
            rows=[r for r in self.scan((210,200,580,700)) if 278<r['point'][0]<410]
            found=next((r for r in rows if norm(r['text'])==self.date_character),None)
            if found:
                self.click(*found['point'],wait_over=True,rate=4)
                co_detect(self,img_ends='mochi_detail')
                if self.match('date_character'): return True
                # Selection/scroll settling may reorder MAD's list. Search again
                # on the new frame instead of replaying the old row coordinate.
                previous=None
                continue
            signature=tuple(r['text'] for r in rows)
            if signature==previous: break
            previous=signature
            self.swipe(*( (470,270,470,660) if direction<0 else (470,650,470,265)),.5,1.2)
            self.update_screenshot_array()
    return False

def implement(self):
    params=self.task_params['dating']
    target=params['character']
    if not target: raise ValueError('请在任务配置中选择约会角色。')
    contacts(self)
    if not select_character(self,target):
        self.note('伙伴列表未找到 '+target+'，本次跳过。'); return True
    tickets=self.get_resource((520,102,574,136))
    count=min(params['count'],tickets)
    if count<1 or '没有可使用' in self.line((820,560,955,590)):
        self.note('每日免费约会次数已用完。'); return True
    state=co_detect(self,img_ends=['date_map','date_plan','inadequate'],img_reactions={'date_character':(941,577)})
    if state=='inadequate': self.note('约会次数已用完。'); return True
    while state!='date_plan':
        map_id=self.line((555,626,725,673))
        priorities=params['location_priority'].get(map_id,[])
        locations=MAP_LOCATIONS.get(map_id,{})
        candidate=next(((name,locations[name]) for name in priorities if name in locations and
            self.line(locations[name])==name and blue(self,locations[name])<.45),None)
        if candidate is None:
            self.note('当前地图可用优先地点不足三处，保留角色设置。'); self.to_main_page(); return True
        name,area=candidate
        self.date_location_area=area
        state=co_detect(self,img_ends=['date_plan','date_location_selected'],img_reactions={'date_map':centre(area)})
        self.update_screenshot_array()
        if self.match('date_plan'): state='date_plan'
    co_detect(self,img_ends='date_confirm',img_reactions={'date_plan':(1135,547)})
    initial=self.ocr.recognize_int(self,(799,395,835,433),default=1)
    if initial!=count:
        self.click(976 if initial<count else 659,416,count=abs(count-initial),wait_over=True)
    state=co_detect(self,img_ends=['date_result','inadequate'],img_reactions={'date_confirm':(921,538)})
    if state=='date_result':
        self.save_screenshot('dating-result')
        co_detect(self,img_ends='mochi_contacts',img_reactions={'date_result':(1176,40)})
        self.note(f'已与{target}快速约会 {count} 次。',character=target,count=count)
    else: self.note('免费约会次数不足。')
    return True

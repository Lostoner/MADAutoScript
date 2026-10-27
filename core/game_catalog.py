"""Selection data observed on ONEstore MAD 1.10.3; no editable stage/name fields."""
import json
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/'src'/'game_catalog.json'
PROCUREMENT={'数据窃取':('工厂数据',6),'勒索钱财':('隐藏财物',6),'洗衣店袭击':('洗衣店分店',6),'截获快递':('物流终端',5)}
FLARA={'热情的锻炼场':'健身弗拉瑞区域','欲望的赞美堂':'修女弗拉瑞区域','意志的休息处':'女仆弗拉瑞区域','理性的博弈馆':'兔女郎弗拉瑞区域'}

# Ordinary-tab products and gold prices from the user's 2026-10-26 screenshot.
# Stock is read from the game; the screenshot's remaining count is not a limit.
SHOP_ITEMS = {
    'c_battle_log': {'title': 'C级战斗日志', 'price': 100},
    'b_battle_log': {'title': 'B级战斗日志', 'price': 1000},
    'a_battle_log': {'title': 'A级战斗日志', 'price': 5000},
    'sample_essence': {'title': '样品精华', 'price': 10},
    'small_essence': {'title': '小型精华', 'price': 100},
    'medium_essence': {'title': '中型精华', 'price': 500},
}

def data():
    return json.loads(PATH.read_text('utf-8'))

def stage_options(task):
    catalog=data()
    if task=='mad.normal_sweep':
        return {f'normal:{z}-{n}':{'title':f'NORMAL {z}-{n}','target':f'NORMAL{z}-{n}','group':f'区域 {z}','zone':int(z),'cost':catalog['sweep']['normal']['cost']}
                for z,count in catalog['normal_zones'].items() for n in range(1,count+1)}
    categories=PROCUREMENT if task=='mad.procurement_sweep' else {k:(v,5) for k,v in FLARA.items()}
    prefix='procurement' if task=='mad.procurement_sweep' else 'flara'
    return {f'{prefix}:{category}:{n}':{'title':f'{category} · {name}{n}','target':name+str(n),'group':category,'category':category,'category_y':(124,187,251,314)[list(categories).index(category)],'cost':catalog['sweep'][prefix]['cost']}
            for category,(name,count) in categories.items() for n in range(1,count+1)}

def characters():
    return data()['characters']

"""Compatibility names for UI callers; the only task table is core.tasks."""
from core.tasks import TASKS as ROUTINES, CLAIM_MODULES, parameter_summary

def default_routine():
    return {'stamina_claim':{},'normal_sweep':{'plans':[{'stage_id':'normal:9-10','count':1}]},
            'flara_sweep':{'plans':[]},'procurement_sweep':{'plans':[{'stage_id':'procurement:数据窃取:4','count':1}]},
            'gold_shop':{'items':[{'item_id':'c_battle_log','count':1}]},
            'dating':{'character':'','count':3,'location_priority':{'四君子':['渡口','天灯街','华西园'],'赫玛尼塔斯':['DD镇','豆腐街','湖水公园'],'贝尔蒙特':['宴会厅','贝尔蒙特广场','咖啡街']}},
            'claim_all':{'modules':{'activity':False,'pass':True,'mall':True,'tasks':True,'mail':True},'mall_periods':['daily','weekly','monthly']}}

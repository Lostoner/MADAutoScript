"""One MAD function table, following BAAS Baas_thread.func_dict (GPL-3.0)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    resource: str = ''
    supported: bool = True
    default_enabled: bool = False

TASKS = {t.task_id:t for t in (
    TaskSpec('mad.stamina_claim','体力领取','收取累积体力',default_enabled=True),
    TaskSpec('mad.flara_sweep','弗拉瑞区域','能量'),
    TaskSpec('mad.normal_sweep','普通扫荡','普通体力'),
    TaskSpec('mad.procurement_sweep','特别采购','能量'),
    TaskSpec('mad.gold_shop','普通商店','所选普通商品 · 金币'),
    TaskSpec('mad.dating','指定角色约会','每日免费次数'),
    TaskSpec('mad.arena','竞技场','尚未开放',False),
    TaskSpec('mad.event_sweep','活动扫荡','待适配',False),
    TaskSpec('mad.mail','邮箱领取','邮箱奖励'),
    TaskSpec('mad.claim_all','一键领取','所选领取子功能',default_enabled=True),
)}
CLAIM_MODULES={'activity':'活动（等待单独规则）','pass':'通行证','mall':'阿米商城免费物品','tasks':'任务与积分宝箱','mail':'邮箱'}
SWEEP_TASKS=('mad.normal_sweep','mad.flara_sweep','mad.procurement_sweep')

def task_definitions(): return tuple(TASKS.values())

def function_table():
    from module import normal_sweep, flara_sweep, procurement_sweep, stamina_claim, gold_shop, dating, mail, claim_all, restart
    return {'mad.normal_sweep':normal_sweep.implement,'mad.flara_sweep':flara_sweep.implement,
            'mad.procurement_sweep':procurement_sweep.implement,'mad.stamina_claim':stamina_claim.implement,
            'mad.gold_shop':gold_shop.implement,'mad.dating':dating.implement,'mad.mail':mail.implement,
            'mad.claim_all':claim_all.implement,'restart':restart.implement}

def parameter_summary(task_id,routine):
    spec=TASKS[task_id]
    if not spec.supported or task_id in ('mad.mail','mad.stamina_claim'): return spec.resource
    if task_id=='mad.claim_all':
        return '、'.join(v for k,v in CLAIM_MODULES.items() if routine['claim_all']['modules'].get(k)) or '未选择子功能'
    item=routine[task_id[4:]]
    if task_id=='mad.dating': return f'{item["character"] or "未指定角色"} · {item["count"]}次'
    if task_id=='mad.gold_shop':
        from core.game_catalog import SHOP_ITEMS
        return '；'.join(f'{SHOP_ITEMS[p["item_id"]]["title"]} ×{str(p["count"]).upper()}' for p in item['items']) or '未选择商品'
    from core.game_catalog import stage_options
    options=stage_options(task_id)
    return '；'.join(f'{options.get(p["stage_id"],{}).get("title",p["stage_id"])} ×{str(p["count"]).upper()}' for p in item['plans']) or '未选择关卡'

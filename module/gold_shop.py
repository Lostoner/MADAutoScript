"""BAAS common_shop: configured products, native stock and gold availability."""
import re
from core.picture import co_detect
from core.game_catalog import SHOP_ITEMS
from core.mad_features import FEATURES, norm

TITLE_AREA = (479, 169, 680, 195)
COUNT_AREA = (610, 337, 695, 373)
ITEMS_AREA = (700, 120, 1180, 610)
POINTS = {'min': (407, 405), 'plus': (810, 405), 'max': (873, 405),
          'cancel': (525, 575), 'buy': (755, 575)}

def count_text(self):
    return self.line(COUNT_AREA, 'en-us', '0123456789/').split('/', 1)[0].strip()

FEATURES.update({
    'shop_target_dialog': lambda s: s.match('gold_purchase') and norm(s.line(TITLE_AREA)) == norm(s.shop_target),
    'shop_count_readable': lambda s: count_text(s).isdigit(),
})

def set_quantity(self, requested):
    self.click(*POINTS['max'], wait_over=True)
    co_detect(self, img_ends='shop_count_readable')
    available = int(count_text(self))
    desired = available if requested == 'max' else min(requested, available)
    if desired < available:
        self.click(*POINTS['min'], wait_over=True)
        if desired > 1:
            self.click(*POINTS['plus'], count=desired - 1, duration=(desired - 1) * .12, wait_over=True)
    self.update_screenshot_array()
    co_detect(self, img_ends='shop_count_readable', skip_first_screenshot=True)
    return int(count_text(self)) if desired else 0

def get_item_position(self, title):
    """BAAS shop_utils: locate a current, purchasable card on each new frame."""
    rows = self.scan(ITEMS_AREA)
    item = next((r for r in rows if norm(r['text']) == norm(title)), None)
    if item is None:
        self.logger.info('%s 当前未在商品列表中找到，跳过。', title)
        return None
    x, y = item['point']
    # MAD moves sold-out cards to the end. Both stock and clicks must follow
    # the product name, never its original grid slot.
    labels = [norm(r['text']).upper() for r in rows
              if abs(r['point'][0] - x) < 65 and -60 < r['point'][1] - y < 30]
    if any(t in ('SOLDOUT', '售罄', '售馨', '已购买') or re.search(r'可购买0次', t)
           for t in labels):
        self.logger.info('%s 已售罄，跳过。', title)
        return None
    return (x, y)

def prepare_purchase(self, item_id, requested):
    """Open the configured product and set quantity; does not confirm a purchase."""
    product = SHOP_ITEMS[item_id]
    self.shop_target = product['title']
    while co_detect(self, img_ends=['shop_target_dialog', 'normal_shop'],
                    img_reactions={'gold_purchase': POINTS['cancel']}) == 'normal_shop':
        point = get_item_position(self, product['title'])
        if point is None:
            return 0
        self.logger.info('OCR 定位商品：%s @ (%.0f, %.0f)', product['title'], *point)
        self.click(*point, wait_over=True)
    return set_quantity(self, requested)

def return_to_shop(self):
    # BAAS dismisses a purchase notice before returning to the shop list.
    if self.match('inadequate'):
        for row in reversed(self.scan((280, 120, 1080, 610))):
            if row['text'] in ('确认', '确定', '关闭'):
                self.click(*row['point'], wait_over=True)
                break
    co_detect(self, img_ends='normal_shop', img_reactions={
        'reward_popup': (640, 592), 'gold_purchase': POINTS['cancel']})

def implement(self):
    items = self.task_params['gold_shop']['items']
    if not items:
        self.note('普通商店未选择商品。')
        return True
    self.open_page('normal_shop')
    assets = self.line((910, 26, 999, 61), 'en-us', '0123456789,').replace(',', '').strip()
    gold = int(assets) if assets.isdigit() else -1
    purchased = []
    for item in items:
        product = SHOP_ITEMS[item['item_id']]
        requested = item['count']
        if gold >= 0:
            affordable = gold // product['price']
            if not affordable:
                self.logger.info('%s 金币不足，跳过。', product['title'])
                continue
            requested = affordable if requested == 'max' else min(requested, affordable)
        actual = prepare_purchase(self, item['item_id'], requested)
        if actual:
            state = co_detect(self, img_ends=['reward_popup', 'inadequate'], img_reactions={'shop_target_dialog': POINTS['buy']})
            if state == 'reward_popup':
                purchased.append({'item_id': item['item_id'], 'count': actual})
                self.logger.info('已购买 %s ×%s。', product['title'], actual)
                if gold >= 0: gold -= actual * product['price']
            else:
                self.logger.info('%s 当前无法购买，继续其余商品。', product['title'])
        return_to_shop(self)
    text = '；'.join(f'{SHOP_ITEMS[p["item_id"]]["title"]} ×{p["count"]}' for p in purchased)
    self.note('普通商店：' + (text or '所选商品暂无可购买数量。'), purchased=purchased)
    return True

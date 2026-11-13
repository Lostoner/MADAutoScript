"""Categorized, multi-select material browser using the bundled game thumbnails."""
from html import escape

from PyQt5.QtCore import Qt, QSize, QRect, QUrl
from PyQt5.QtGui import QIcon, QColor, QPen, QPainter
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QButtonGroup, QListWidget, QListWidgetItem, QListView,
                            QAbstractItemView, QStyledItemDelegate, QStyle)
from qfluentwidgets import LineEdit, PushButton, PrimaryPushButton

from core.paths import REPO_ROOT
from gui.theme import typography, apply_typography, ui_font

CATEGORIES={'voucher':'装备兑换券','equipment':'基础装备','currency':'通用资源'}


def material_icon(item):
    return QIcon(str(REPO_ROOT/item['icon']))


def material_tooltip(item):
    parts=[CATEGORIES[item['category']]]
    if item['tier']: parts.append('T'+str(item['tier']))
    if item['slot']: parts.append(item['slot'])
    source=QUrl.fromLocalFile(str(REPO_ROOT/item['icon'])).toString()
    pending='<br>来源待实机补验' if item['verification']=='public_table_pending_live' else ''
    return (f'<img src="{escape(source,quote=True)}" width="80"><br><b>{escape(item["name"])}</b><br>'
            +escape(' · '.join(parts))+pending)


class MaterialTileDelegate(QStyledItemDelegate):
    """Fixed image/name/status slots keep every localized name fully visible."""
    def __init__(self, items, theme, parent):
        super().__init__(parent)
        self.items,self.theme=items,theme

    def paint(self, painter, option, index):
        item=self.items[index.data(Qt.UserRole)]
        s,c=self.theme.surfaces,self.theme.colors
        selected=bool(option.state & QStyle.State_Selected)
        enabled=bool(option.state & QStyle.State_Enabled)
        focused=bool(option.state & (QStyle.State_HasFocus|QStyle.State_MouseOver))
        rect=option.rect.adjusted(1,1,-1,-1)
        painter.save(); painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(s['selected'] if selected else s['card']))
        painter.setPen(QPen(QColor(s['accent'] if selected or (focused and enabled) else s['line']),2 if selected else 1))
        painter.drawRoundedRect(rect,8,8)
        painter.setOpacity(1 if enabled else .45)
        index.data(Qt.DecorationRole).paint(painter,QRect(rect.center().x()-32,rect.top()+5,64,64))
        painter.setOpacity(1)
        painter.setFont(ui_font(14)); painter.setPen(QColor(c['text'] if enabled else s['muted']))
        painter.drawText(QRect(rect.left()+6,rect.top()+73,rect.width()-12,21),Qt.AlignCenter,item['name'])
        painter.setFont(ui_font(12)); painter.setPen(QColor(c['text__warning'] if enabled and
                        item['verification']=='public_table_pending_live' else s['muted']))
        painter.drawText(QRect(rect.left()+6,rect.top()+96,rect.width()-12,18),Qt.AlignCenter,index.data(Qt.UserRole+1))
        if selected:
            painter.setFont(ui_font(16)); painter.setPen(QColor(s['accent']))
            painter.drawText(QRect(rect.right()-26,rect.top()+5,20,22),Qt.AlignCenter,'✓')
        painter.restore()


class MaterialPicker(QDialog):
    def __init__(self, items, existing, theme, parent=None, *, category='voucher', tier=2):
        super().__init__(parent)
        self.items,self.existing,self.theme=items,set(existing),theme
        self.category,self.tier=category,tier
        self.selection=[]
        self.setWindowTitle('选择素材')
        available=self.screen().availableGeometry()
        self.setMinimumSize(min(720,available.width()),min(480,available.height()))
        self.resize(min(920,available.width()),min(690,available.height()))
        outer=QVBoxLayout(self); outer.setContentsMargins(22,18,22,18); outer.setSpacing(12)
        outer.addWidget(typography(QLabel('选择需要的素材'),22,True))
        self.search=LineEdit(self)
        self.search.setPlaceholderText('搜索全部素材，例如：T3 耳环、项链、信用点')
        self.search.setClearButtonEnabled(True); self.search.setAccessibleName('搜索全部素材')
        outer.addWidget(self.search)
        categories=QHBoxLayout(); categories.setSpacing(8)
        self.category_group=QButtonGroup(self); self.category_buttons={}
        for key,title in {'all':'全部素材',**CATEGORIES}.items():
            count=sum(key=='all' or i['category']==key for i in items.values())
            button=self.filter_button(f'{title}  {count}',self.category_group)
            button.clicked.connect(lambda _,k=key:self.choose_category(k))
            categories.addWidget(button); self.category_buttons[key]=button
        categories.addStretch(); outer.addLayout(categories)
        tier_row=QHBoxLayout(); tier_row.setSpacing(8)
        self.tier_group=QButtonGroup(self); self.tier_buttons={}
        self.tier_label=QLabel('阶级'); tier_row.addWidget(self.tier_label)
        for key,title in ((None,'全部阶级'),(2,'T2'),(3,'T3'),(4,'T4'),(5,'T5')):
            button=self.filter_button(title,self.tier_group)
            button.clicked.connect(lambda _,k=key:self.choose_tier(k))
            tier_row.addWidget(button); self.tier_buttons[key]=button
        tier_row.addStretch(); outer.addLayout(tier_row)
        self.heading=QLabel(); outer.addWidget(self.heading)
        self.grid=QListWidget(self); self.grid.setObjectName('materialGrid')
        self.grid.setViewMode(QListView.IconMode); self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static); self.grid.setWrapping(True)
        self.grid.setSelectionMode(QAbstractItemView.MultiSelection)
        self.grid.setIconSize(QSize(64,64)); self.grid.setGridSize(QSize(200,128)); self.grid.setSpacing(6)
        self.grid.setWordWrap(True); self.grid.setUniformItemSizes(True)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setAccessibleName('素材图标列表，点击或空格切换选择')
        self.grid.setItemDelegate(MaterialTileDelegate(items,theme,self.grid))
        self.rows={}
        for ref,item in items.items():
            suffix=('已添加' if ref in self.existing else '来源待补验' if item['verification']=='public_table_pending_live'
                    else 'T1 · '+item['slot'] if item['category']=='equipment' else '')
            row=QListWidgetItem(material_icon(item),item['name']+('\n'+suffix if suffix else ''))
            row.setData(Qt.UserRole,ref); row.setData(Qt.UserRole+1,suffix); row.setToolTip(material_tooltip(item))
            row.setTextAlignment(Qt.AlignCenter); row.setSizeHint(QSize(188,120))
            if ref in self.existing: row.setFlags(Qt.NoItemFlags)
            self.grid.addItem(row); self.rows[ref]=row
        outer.addWidget(self.grid,1)
        self.empty=QLabel('没有找到素材。试试部位名称，如“耳环”，或清空搜索。')
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True); outer.addWidget(self.empty,1)
        footer=QHBoxLayout()
        self.selected_note=QLabel(); self.selected_note.setWordWrap(True); footer.addWidget(self.selected_note,1)
        self.clear_button=PushButton('清空选择'); footer.addWidget(self.clear_button)
        self.cancel_button=PushButton('取消'); footer.addWidget(self.cancel_button)
        self.add_button=PrimaryPushButton('添加所选'); self.add_button.setDefault(True); footer.addWidget(self.add_button)
        outer.addLayout(footer)
        self.search.textChanged.connect(self.filter_items)
        self.grid.itemSelectionChanged.connect(self.selection_changed)
        self.clear_button.clicked.connect(self.clear_selection)
        self.cancel_button.clicked.connect(self.reject); self.add_button.clicked.connect(self.accept)
        theme.apply_surface(self); theme.apply_surface(self.grid,'input'); theme.apply_surface(self.grid.viewport(),'input')
        s,c=theme.surfaces,theme.colors
        self.setStyleSheet(f'QPushButton#materialFilter {{padding:7px 14px;border:1px solid {s["line"]};'
            f'border-radius:6px;background:{s["card"]};color:{c["text"]};}} '
            f'QPushButton#materialFilter:checked {{background:{s["selected"]};border-color:{s["accent"]};color:{s["accent"]};}} '
            f'QPushButton#materialFilter:hover {{border-color:{s["accent"]};}} '
            f'QListWidget#materialGrid {{background:{s["page"]};color:{c["text"]};border:0;outline:0;}} ')
        self.grid.verticalScrollBar().setStyleSheet(
            f'QScrollBar:vertical {{background:{s["page"]};width:10px;margin:0;}} '
            f'QScrollBar::handle:vertical {{background:{s["line"]};min-height:24px;border-radius:4px;}} '
            f'QScrollBar::handle:vertical:hover {{background:{s["muted"]};}} '
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}')
        apply_typography(self); self.filter_items(); self.search.setFocus()

    def filter_button(self, text, group):
        button=QPushButton(text,self); button.setObjectName('materialFilter')
        button.setCheckable(True); button.setAutoDefault(False); button.setCursor(Qt.PointingHandCursor)
        group.addButton(button)
        return button

    def choose_category(self, category):
        self.category=category
        self.search.blockSignals(True); self.search.clear(); self.search.blockSignals(False)
        self.filter_items()

    def choose_tier(self, tier):
        self.tier=tier; self.filter_items()

    def filter_items(self):
        words=self.search.text().strip().casefold().split()
        searching=bool(words)
        self.category_buttons['all' if searching else self.category].setChecked(True)
        self.tier_buttons[self.tier].setChecked(True)
        for control in (self.tier_label,*self.tier_buttons.values()):
            control.setVisible(not searching and self.category=='voucher')
        self.grid.blockSignals(True)
        visible=[]
        for ref,item in self.items.items():
            haystack=' '.join((item['name'],item['slot'],CATEGORIES[item['category']],
                               'T'+str(item['tier']) if item['tier'] else '')).casefold()
            match=(all(word in haystack for word in words) if searching else
                   (self.category=='all' or item['category']==self.category) and
                   (self.category!='voucher' or self.tier is None or item['tier']==self.tier))
            row=self.rows[ref]; row.setHidden(not match); row.setSelected(ref in self.selection)
            if match: visible.append(ref)
        self.grid.blockSignals(False)
        self.visible_refs=visible
        available=sum(r not in self.existing for r in visible)
        title='搜索结果' if searching else ('全部素材' if self.category=='all' else CATEGORIES[self.category])
        if not searching and self.category=='voucher' and self.tier: title+=' · T'+str(self.tier)
        self.heading.setText(f'{title}  ·  {len(visible)} 项，{available} 项可添加')
        self.empty.setVisible(not visible)
        self.grid.setVisible(bool(visible))
        self.grid.scrollToTop(); self.update_selection_note()

    def selection_changed(self):
        visible=set(self.visible_refs)
        selected=[r for r in self.visible_refs if self.rows[r].isSelected() and r not in self.existing]
        self.selection=[r for r in self.selection if r not in visible or r in selected]
        self.selection.extend(r for r in selected if r not in self.selection)
        self.update_selection_note()

    def update_selection_note(self):
        count=len(self.selection)
        names=[self.items[r]['name'] for r in self.selection]
        self.selected_note.setText(('已选 '+str(count)+' 项：'+'、'.join(names[:2])+(' 等' if count>2 else '')) if count
                                   else '可跨分类多选；已添加的素材不重复添加。')
        self.selected_note.setToolTip('\n'.join(names))
        self.add_button.setEnabled(bool(count)); self.clear_button.setEnabled(bool(count))
        self.add_button.setText(f'添加 {count} 项' if count else '添加所选')

    def clear_selection(self):
        self.selection=[]; self.grid.blockSignals(True); self.grid.clearSelection(); self.grid.blockSignals(False)
        self.update_selection_note()

    def accept(self):
        if self.selection: super().accept()

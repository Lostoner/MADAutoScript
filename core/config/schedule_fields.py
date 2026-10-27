"""Qt/device-free schedule form values, GPL-3.0-only."""
import re

def parse_periods(text):
    result=[]
    if not text.strip():
        return result
    for part in re.split(r'[;；]',text):
        clocks=part.strip().split('-')
        if len(clocks)!=2:
            raise ValueError('禁用时段格式为 23:00-07:00；多个时段用 ; 分隔。')
        period=[]
        for clock in clocks:
            if not re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?',clock.strip()):
                raise ValueError('时间需为 HH:MM 或 HH:MM:SS。')
            values=[int(v) for v in clock.strip().split(':')]
            if len(values)==2:
                values.append(0)
            if not (0<=values[0]<24 and 0<=values[1]<60 and 0<=values[2]<60):
                raise ValueError('禁用时间超出有效范围。')
            period.append(values)
        if period in result:
            raise ValueError('禁用时段重复。')
        result.append(period)
    return result

def format_periods(periods):
    return '; '.join('-'.join(':'.join(f'{v:02d}' for v in clock) for clock in period) for period in periods)

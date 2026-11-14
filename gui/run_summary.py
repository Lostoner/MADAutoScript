"""Read-only presentation of existing worker results; no execution state or storage."""

STATE_TEXT = {'idle': '待机', 'starting': '正在连接', 'running': '正在执行',
              'waiting': '等待到期任务', 'stopping': '正在停止…',
              'stopped': '已停止', 'succeeded': '本轮结束', 'failed': '执行未完成'}
RESULT_TEXT = {'SUCCESS': '已完成', 'NOTHING_TO_CLAIM': '无可领', 'SKIPPED': '已跳过',
               'PARTIAL': '有余项', 'FAILED': '未完成', 'NEEDS_ATTENTION': '需处理',
               'STOPPED': '已停止'}


def brief_error(message):
    """Keep the actual exception message; full traceback remains in detailed logs."""
    lines = str(message or '').strip().splitlines()
    if not lines:
        return ''
    text = lines[-1].strip()
    return text if len(text) <= 240 else text[:237] + '…'


def result_title(state, tasks):
    if state == 'succeeded':
        statuses = {row.get('status') for row in tasks}
        if statuses & {'FAILED', 'NEEDS_ATTENTION'}:
            return '本轮结束 · 需处理'
        if 'PARTIAL' in statuses:
            return '本轮结束 · 有余项'
    return STATE_TEXT.get(state, state)


def result_lines(tasks):
    """Report quantities only when the worker actually supplied them."""
    lines = []
    for row in tasks:
        if row.get('status') not in ('PARTIAL', 'FAILED', 'NEEDS_ATTENTION', 'SKIPPED'):
            continue
        name = row.get('event_name') or row.get('task_id', '')
        reason = brief_error(row.get('reason'))
        remaining = row.get('remaining')
        if isinstance(remaining, list) and 'completed' in row:
            left = (f'剩余 {sum(p["count"] for p in remaining)} 次'
                    if all(type(p.get('count')) is int for p in remaining)
                    else f'剩余 {len(remaining)} 个关卡')
            reason = f'本次完成 {row["completed"]} 次，{left}' + ('；' + reason if reason else '')
        lines.append(name + '：' + (reason or RESULT_TEXT.get(row.get('status'), '')))
    return lines

"""Offline anonymous HTML using the same explanation as live and history views."""
from html import escape

from .storage import safe_snapshot
from .reports import upgrade, explain


def html_report(snapshot):
    data = safe_snapshot(snapshot)
    history = [upgrade(row) for row in data.get('history', [])]

    def paragraph(value, cls=''):
        return '<p class="' + cls + '">' + escape(str(value)) + '</p>'

    cards, rows = [], []
    for index, row in enumerate(history):
        brief = explain(row)
        anchor = 'record-' + str(index)
        title = (row.get('source_alias') or '历史目标') + ' · ' + (row.get('model') or '型号未记录')
        cards.append('<article id="' + anchor + '"><h2>' + escape(title) + '</h2>'
                     + paragraph(brief['evaluated_at'] or '时间未记录', 'muted')
                     + '<h3>' + escape(brief['headline']) + '</h3>'
                     + ''.join(paragraph(brief[key]) for key in ('observed', 'reference_note'))
                     + ''.join(paragraph(line) for key in ('coverage', 'diagnostics', 'format_notes') for line in brief[key])
                     + paragraph(brief['next_step'], 'next-step')
                     + paragraph(brief['limitations'], 'muted')
                     + '<h4>能力分项与专项结果</h4>'
                     + ''.join(paragraph(line) for line in brief['task_summary'])
                     + '<details><summary>专业详情</summary>'
                     + paragraph(brief['identity'])
                     + ''.join(paragraph(line) for line in (*brief['details'], *brief['task_details']))
                     + paragraph('证据：' + row['evidence_level'] + ' · experimental')
                     + '</details></article>')
        values = (row.get('evaluated_at', ''), row.get('source_alias', ''), row.get('model', ''),
                  row.get('mode', ''), row.get('status', ''))
        rows.append('<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in values)
                    + '<td><a href="#' + anchor + '">查看本轮报告</a></td></tr>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>Codex Lens · 模型检测报告</title><style>'
            'body{font:15px system-ui,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#183541;overflow-wrap:anywhere}'
            'article{border:1px solid #dce5e9;border-radius:12px;padding:18px;margin:18px 0}'
            'table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid #ddd;padding:9px;text-align:left}'
            '.muted{color:#526773}.next-step{font-weight:600}.table-wrap{overflow-x:auto}'
            '@media print{article{break-inside:avoid}details>*{display:block!important}}'
            '</style><h1>Codex Lens · 模型检测报告</h1>'
            '<p>匿名实验性结果，不认证模型身份。不同任务或参数不可直接排名。</p>'
            '<h2>检测记录</h2><div class="table-wrap"><table><thead><tr><th>时间</th><th>匿名目标</th>'
            '<th>型号</th><th>任务</th><th>状态</th><th>报告</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>'
            + ''.join(cards or ['<p>尚无检测记录。</p>']) + '</html>')

"""Render the Markdown guide from the same offline content used by the app."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render():
    guide = json.loads((ROOT / 'relay_auditor/web/manual/content.json').read_text(encoding='utf-8'))
    lines = ['# ' + guide['title'], '', guide['intro'], '', '在桌面窗口左侧点击「操作手册」可离线阅读本手册。', '']
    for chapter in guide['chapters']:
        lines.extend(['## ' + chapter['title'], '', chapter['purpose'], ''])
        lines.extend(f'{index}. {step}' for index, step in enumerate(chapter['steps'], 1))
        lines.extend(['', '**预期结果**　' + chapter['expected'], '', chapter['tip'], '',
                      f'![{chapter["title"]}的合成界面截图](../relay_auditor/web/manual/{chapter["image"]})', '',
                      '合成示例 · ' + chapter['caption'], ''])
    return '\n'.join(lines)


if __name__ == '__main__':
    (ROOT / 'docs/USER_MANUAL.md').write_text(render(), encoding='utf-8')

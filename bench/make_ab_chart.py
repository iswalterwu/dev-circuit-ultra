from __future__ import annotations

from pathlib import Path

W, H = 1424, 820
BG = "#fffdf8"
INK = "#102a43"
MUTED = "#486581"
SOFT = "#627d98"
LINE = "#d9e2ec"
CARD = "#f8fafc"
BLUE = "#1f4fd8"
AMBER = "#b45309"
TRACK = "#e5edf5"
RED = "#b42318"
GREEN = "#2e7d32"

COPY = {
    "en": {
        "badge": "OPEN A/B  /  BLIND ARTIFACT REVIEW  /  2026-11-06",
        "title": "One open brief. Two loops.",
        "subtitle": "Same fixture, same open prompt, same model. A blind reviewer scored the final repos.",
        "score": "Blind rubric",
        "score_note": "1–5 per dimension, 30 total",
        "cost": "Model cost",
        "cost_note": "Lower is better",
        "time": "Wall time",
        "time_note": "Includes model latency",
        "clean": "Closeout",
        "clean_note": "Uncommitted deliverables; lower is better",
        "dev": "Dev-circuit-ultra",
        "openspec": "OpenSpec 1.15",
        "score_delta": "+1 point",
        "cost_delta": "30% lower",
        "time_delta": "3% faster",
        "clean_delta": "clean vs 11 uncommitted",
        "footer": "n=1 · no hidden acceptance · one end-to-end session per skill · scores are artifact judgments, not a statistical benchmark. Source: bench/results_open_ab.json",
    },
    "zh": {
        "badge": "开放 A/B  /  最终交付物盲评  /  2026-11-06",
        "title": "同一个开放问题，两种 loop。",
        "subtitle": "同一 fixture、同一开放提示、同一模型；评审只看最终仓库。",
        "score": "盲评总分",
        "score_note": "每项 1–5 分，共 30 分",
        "cost": "模型成本",
        "cost_note": "越低越好",
        "time": "实际耗时",
        "time_note": "包含模型延迟",
        "clean": "收尾",
        "clean_note": "未提交交付物；越低越好",
        "dev": "Dev-circuit-ultra",
        "openspec": "OpenSpec 1.15",
        "score_delta": "高 1 分",
        "cost_delta": "低 30%",
        "time_delta": "快 3%",
        "clean_delta": "干净 vs 11 条未提交",
        "footer": "n=1 · 没有隐藏验收 · 每个 skill 一次端到端会话 · 分数是交付物判断，不是统计基准。来源：bench/results_open_ab.json",
    },
}


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card(x: int, y: int, title: str, note: str, rows, maximum: float, delta: str, delta_color: str) -> str:
    out = [
        f'<rect x="{x}" y="{y}" width="624" height="280" rx="6" fill="{CARD}" stroke="{LINE}"/>',
        f'<text x="{x + 32}" y="{y + 42}" font-size="22" font-weight="700" fill="{INK}">{esc(title)}</text>',
        f'<text x="{x + 32}" y="{y + 66}" font-size="14" fill="{SOFT}">{esc(note)}</text>',
    ]
    bar_x = x + 176
    bar_w = 300
    for index, (label, value, display, color) in enumerate(rows):
        row_y = y + 112 + index * 46
        width = max(2, round(value / maximum * bar_w))
        out.extend([
            f'<text x="{x + 32}" y="{row_y + 15}" font-size="15" fill="{INK}">{esc(label)}</text>',
            f'<rect x="{bar_x}" y="{row_y}" width="{bar_w}" height="20" rx="3" fill="{TRACK}"/>',
            f'<rect x="{bar_x}" y="{row_y}" width="{width}" height="20" rx="3" fill="{color}"/>',
            f'<text x="{bar_x + bar_w + 18}" y="{row_y + 15}" font-size="15" font-family="Consolas, monospace" font-weight="700" fill="{INK}">{esc(display)}</text>',
        ])
    out.extend([
        f'<text x="{x + 32}" y="{y + 246}" font-size="14" font-weight="700" fill="{delta_color}">{esc(delta)}</text>',
    ])
    return "\n".join(out)


def make(lang: str) -> str:
    c = COPY[lang]
    score = card(64, 156, c["score"], c["score_note"], [
        (c["dev"], 27, "27/30", BLUE),
        (c["openspec"], 26, "26/30", AMBER),
    ], 30, c["score_delta"], GREEN)
    cost = card(736, 156, c["cost"], c["cost_note"], [
        (c["dev"], 0.074322, "$0.0743", BLUE),
        (c["openspec"], 0.105972, "$0.1060", AMBER),
    ], 0.12, c["cost_delta"], GREEN)
    time = card(64, 464, c["time"], c["time_note"], [
        (c["dev"], 408.9, "409s", BLUE),
        (c["openspec"], 421.0, "421s", AMBER),
    ], 500, c["time_delta"], GREEN)
    clean = card(736, 464, c["clean"], c["clean_note"], [
        (c["dev"], 0, "0", BLUE),
        (c["openspec"], 11, "11", AMBER),
    ], 12, c["clean_delta"], GREEN)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(c['title'])}">
  <rect width="{W}" height="{H}" fill="{BG}"/>
  <rect x="24" y="24" width="{W - 48}" height="{H - 48}" fill="none" stroke="{INK}" stroke-width="2"/>
  <text x="64" y="68" font-size="12" font-weight="700" letter-spacing="1.4" fill="{BLUE}">{esc(c['badge'])}</text>
  <text x="64" y="122" font-size="38" font-weight="700" fill="{INK}">{esc(c['title'])}</text>
  <text x="64" y="150" font-size="17" fill="{MUTED}">{esc(c['subtitle'])}</text>
  {score}
  {cost}
  {time}
  {clean}
  <line x1="64" y1="758" x2="{W - 64}" y2="758" stroke="{LINE}"/>
  <text x="64" y="784" font-size="13" fill="{SOFT}">{esc(c['footer'])}</text>
</svg>
'''


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    for lang in ("en", "zh"):
        out = root / "assets" / f"ab-comparison-{lang}.svg"
        out.write_text(make(lang), encoding="utf-8")
        print(out)


if __name__ == "__main__":
    main()

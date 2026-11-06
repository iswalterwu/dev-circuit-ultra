from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 20
DURATION = 60.0
BG = "#fffdf8"
INK = "#102a43"
MUTED = "#486581"
SOFT = "#627d98"
BLUE = "#1f4fd8"
AMBER = "#ffb703"
GREEN = "#2e7d32"
TERM_BG = "#0b1f33"
TERM_FG = "#d9e2ec"

ROOT = Path(__file__).resolve().parent
FONT_DIR = Path("C:/Windows/Fonts")
FONT_UI = FONT_DIR / "segoeui.ttf"
FONT_UI_BOLD = FONT_DIR / "segoeuib.ttf"
FONT_MONO = FONT_DIR / "consola.ttf"
FONT_CN = FONT_DIR / "msyh.ttc"
FONT_CN_BOLD = FONT_DIR / "msyhbd.ttc"

TEXT = {
    "en": {
        "eyebrow": "DEV-CIRCUIT-ULTRA  /  60-SECOND WALKTHROUGH",
        "intro": [
            "Less context.",
            "Less ceremony.",
            "More shipping.",
        ],
        "intro_sub": "A development loop with the ceremony removed.",
        "intro_kicker": "less context / more shipping",
        "problem": [
            "$ why this loop?",
            "",
            "stale design docs  ->  the agent guesses",
            "rejected options   ->  the repo grows",
            "old history        ->  every turn re-reads it",
        ],
        "loop": [
            "$ dev-circuit-ultra",
            "route: feature",
            "",
            "01  design clarify   current design + spec delta",
            "02  one slice        only the next end-to-end step",
            "03  build + verify   code + tests + checks",
            "04  review once      independent reviewer, real diff",
            "05  closeout         merge specs, delete the card",
        ],
        "demo": [
            "$ python demo/run_demo.py",
            "",
            "PASS dev-circuit-ultra demo",
            "project:  D:\\code\\my-app",
            "ledger:   D:\\ledgers\\my-app",
            "final spec lines: 7",
            "checks: pytest, doc_guard, spec_check",
            "",
            "boundaries: no ledger in project",
        ],
        "boundary": [
            "project/                    ledger/  (private, outside)",
            "  specs/                      entries/",
            "  docs/requirements/          schema.md",
            "  no ledger/                  append-only",
            "",
            "dev agent: read project       archivist: write ledger",
            "human: the only bridge between them",
        ],
        "ab": [
            "$ A/B: one open brief, two loops",
            "",
            "rubric  27/30   vs 26/30",
            "cost    $0.074  vs $0.106",
            "time    409s    vs 421s",
            "clean   0       vs 11 uncommitted",
            "",
            "n=1; blind artifact review",
        ],
        "close": [
            "$ python scripts/doc_guard.py",
            "OK",
            "",
            "close add-report",
            "card deleted; requirements merged",
            "",
            "The current design is the source.",
        ],
        "cta": [
            "Less context. Less ceremony. More shipping.",
            "github.com/iswalterwu/dev-circuit-ultra",
        ],
        "steps": ["design", "slice", "build", "review", "close"],
        "figure": "A development loop with the ceremony removed.",
    },
    "zh": {
        "eyebrow": "DEV-CIRCUIT-ULTRA  /  60 秒演示",
        "intro": [
            "更少上下文。",
            "更少流程。",
            "更多交付。",
        ],
        "intro_sub": "通过更少的上下文占用实现增效减负，一个去掉繁琐流程的开发loop。",
        "intro_kicker": "更少上下文 / 更多交付",
        "problem": [
            "$ 为什么需要这个 loop？",
            "",
            "旧设计留在仓库  ->  agent 只能猜",
            "被否方案越积越多  ->  上下文越来越脏",
            "每轮重读历史  ->  成本高，决策慢",
        ],
        "loop": [
            "$ dev-circuit-ultra",
            "route: feature",
            "",
            "01  设计澄清        现行设计 + 规格变化",
            "02  单个切片        只做下一个端到端切片",
            "03  实现 + 验证     代码 + 测试 + 检查",
            "04  独立审核        只审现行设计和真实 diff",
            "05  收尾合并        合并规格，删除卡片",
        ],
        "demo": [
            "$ python demo/run_demo.py",
            "",
            "PASS dev-circuit-ultra demo",
            "project:  D:\\code\\my-app",
            "ledger:   D:\\ledgers\\my-app",
            "final spec lines: 7",
            "checks: pytest, doc_guard, spec_check",
            "",
            "boundaries: 项目里没有 ledger",
        ],
        "boundary": [
            "project/                    ledger/  (私有，项目外)",
            "  specs/                      entries/",
            "  docs/requirements/          schema.md",
            "  没有 ledger/                append-only",
            "",
            "开发 agent：只读项目          archivist：只写账本",
            "human：唯一的桥",
        ],
        "ab": [
            "$ A/B: one open brief, two loops",
            "",
            "评分    27/30   vs 26/30",
            "成本    $0.074  vs $0.106",
            "耗时    409s    vs 421s",
            "收尾    干净    vs 11 条未提交",
            "",
            "n=1；盲评最终交付物",
        ],
        "close": [
            "$ python scripts/doc_guard.py",
            "OK",
            "",
            "close add-report",
            "删除卡片；规格已合并",
            "",
            "设计是唯一现行源。",
        ],
        "cta": [
            "通过更少的上下文占用实现增效减负，",
            "一个去掉繁琐流程的开发loop。",
            "github.com/iswalterwu/dev-circuit-ultra",
        ],
        "steps": ["设计", "切片", "实现", "审核", "收尾"],
        "figure": "项目里只留现行设计，历史在项目外。",
    },
}


def font(size: int, *, bold: bool = False, cn: bool = False, mono: bool = False):
    if mono:
        path = FONT_MONO
    elif cn:
        path = FONT_CN_BOLD if bold else FONT_CN
    else:
        path = FONT_UI_BOLD if bold else FONT_UI
    return ImageFont.truetype(str(path), size)


def text(draw: ImageDraw.ImageDraw, xy, value, *, size=24, fill=INK, bold=False, cn=False, mono=False, anchor=None):
    draw.text(xy, value, font=font(size, bold=bold, cn=cn, mono=mono), fill=fill, anchor=anchor)


def terminal_frame(lang: str, title: str, lines: list[tuple[float, str]], elapsed: float, active_step: int) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([24, 24, W - 24, H - 24], outline=INK, width=2)

    text(draw, (48, 42), TEXT[lang]["eyebrow"], size=12, fill=BLUE, bold=True, cn=lang == "zh")
    text(draw, (W - 48, 42), "60s", size=12, fill=SOFT, bold=True, anchor="ra")

    x0, y0, x1, y1 = 64, 80, W - 64, 612
    draw.rounded_rectangle([x0, y0, x1, y1], radius=6, fill=TERM_BG)
    draw.rectangle([x0, y0, x1, y0 + 44], fill="#07172a")
    for i, color in enumerate(("#ff8fa3", "#ffd93d", "#7ed957")):
        draw.ellipse([x0 + 20 + i * 20, y0 + 17, x0 + 30 + i * 20, y0 + 27], fill=color)
    text(draw, (x0 + 82, y0 + 15), title, size=13, fill="#9fb3c8", mono=True)

    y = y0 + 76
    line_height = 36
    for at, line in lines:
        if elapsed < at:
            continue
        is_command = line.startswith("$")
        use_cn = lang == "zh" and any("\u4e00" <= ch <= "\u9fff" for ch in line)
        text(
            draw,
            (x0 + 32, y),
            line,
            size=20 if is_command else 19,
            fill="#ffd93d" if is_command else TERM_FG,
            mono=is_command,
            cn=use_cn,
        )
        y += line_height

    if int(elapsed * 2) % 2 == 0:
        draw.rectangle([x0 + 32, y + 2, x0 + 44, y + 22], fill="#ffd93d")

    # Bottom five-step strip.
    base_y = 650
    colors = [BLUE, AMBER, BLUE, AMBER, BLUE]
    x = 64
    for i, label in enumerate(TEXT[lang]["steps"]):
        selected = i == active_step
        draw.rounded_rectangle([x, base_y - 18, x + 208, base_y + 18], radius=4, fill="#eef4fb" if selected else BG, outline=colors[i] if selected else "#d9e2ec", width=2)
        text(draw, (x + 14, base_y - 9), f"{i + 1:02d}", size=12, fill=colors[i], bold=True, mono=True)
        text(draw, (x + 48, base_y - 10), label, size=15, fill=INK if selected else MUTED, bold=selected, cn=lang == "zh")
        x += 224
    return image


def intro_frame(lang: str, elapsed: float) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([24, 24, W - 24, H - 24], outline=INK, width=2)
    text(draw, (64, 64), TEXT[lang]["eyebrow"], size=12, fill=BLUE, bold=True, cn=lang == "zh")

    y = 150
    for i, line in enumerate(TEXT[lang]["intro"]):
        if elapsed > 0.35 + i * 0.35:
            text(draw, (64, y), line, size=64, fill=INK, bold=True, cn=lang == "zh")
        y += 78
    if elapsed > 1.6:
        text(draw, (64, 458), TEXT[lang]["intro_sub"], size=24, fill=MUTED, cn=lang == "zh")
    if elapsed > 2.2:
        text(draw, (64, 526), "dev-circuit-ultra", size=18, fill=BLUE, bold=True, mono=True)
        text(draw, (64, 558), TEXT[lang]["intro_kicker"], size=16, fill=SOFT, cn=lang == "zh")

    # Simple sun/ground echo of the banner, kept clear of the frame.
    draw.rectangle([1060, 560, 1156, 576], fill="#7ed957")
    draw.rectangle([1000, 592, 1200, 608], fill="#4caf50")
    draw.ellipse([1080, 140, 1180, 240], fill=AMBER)
    draw.rectangle([1120, 112, 1140, 140], fill=AMBER)
    draw.rectangle([1120, 240, 1140, 268], fill=AMBER)
    return image


def render(lang: str, out: Path) -> None:
    steps = TEXT[lang]["steps"]
    scenes: list[tuple[float, float, Callable[[float], Image.Image]]] = [
        (0, 4, lambda t: intro_frame(lang, t)),
        (4, 10, lambda t: terminal_frame(lang, "problem", [(0.2, line) for line in TEXT[lang]["problem"]], t, 0)),
        (10, 18, lambda t: terminal_frame(lang, "the loop", [(0.2 + i * 0.35, line) for i, line in enumerate(TEXT[lang]["loop"])], t, min(4, int((t - 10) / 1.6)))),
        (18, 30, lambda t: terminal_frame(lang, "deterministic demo", [(0.2 + i * 0.7, line) for i, line in enumerate(TEXT[lang]["demo"])], t, 1)),
        (30, 42, lambda t: terminal_frame(lang, "one boundary", [(0.2 + i * 0.55, line) for i, line in enumerate(TEXT[lang]["boundary"])], t, 3)),
        (42, 50, lambda t: terminal_frame(lang, "A/B", [(0.2 + i * 0.45, line) for i, line in enumerate(TEXT[lang]["ab"])], t, 4)),
        (50, 55, lambda t: terminal_frame(lang, "closeout", [(0.2 + i * 0.55, line) for i, line in enumerate(TEXT[lang]["close"])], t, 4)),
        (55, 60, lambda t: terminal_frame(lang, "ship", [(0.2 + i * 0.55, line) for i, line in enumerate(TEXT[lang]["cta"])], t, 4)),
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    if not writer.isOpened():
        raise SystemExit(f"could not open video writer: {out}")

    total_frames = int(FPS * DURATION)
    for index in range(total_frames):
        elapsed = index / FPS
        frame = None
        for start, end, build in scenes:
            if start <= elapsed < end:
                frame = build(elapsed - start)
                break
        if frame is None:
            frame = scenes[-1][2](DURATION - scenes[-1][0])
        writer.write(np.asarray(frame)[:, :, ::-1])
    writer.release()
    webm = out.with_suffix(".webm")
    transcode(out, webm)
    print(f"{out}  {DURATION:.0f}s  {total_frames} frames")
    print(f"{webm}  webm")


def transcode(src: Path, dst: Path) -> None:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise SystemExit(f"could not open webm writer: {dst}")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame)
    cap.release()
    writer.release()


def poster(lang: str, out: Path) -> None:
    image = intro_frame(lang, 3.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT.parent / "assets")
    args = parser.parse_args()
    for lang in ("en", "zh"):
        render(lang, args.out_dir / f"demo-60s-{lang}.mp4")
        poster(lang, args.out_dir / f"demo-60s-poster-{lang}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

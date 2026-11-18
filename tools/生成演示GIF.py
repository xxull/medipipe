# -*- coding: utf-8 -*-
"""
把真实命令的输出录成 GIF（终端风格）
=========================================================================
不摆拍：先真的跑命令，把 stdout 抓下来，再逐行"打"到图上。
所以 GIF 里出现的数字就是当时库里真实的数字。

用法
-------------------------------------------------------------------------
    python tools\\生成演示GIF.py                 # 生成到 docs/gif/
    python tools\\生成演示GIF.py --repo <目录>   # 用别的库跑（默认当前仓库）

依赖：pillow（见 requirements-dev.txt）
=========================================================================
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

W, H = 1120, 640
BG = (13, 17, 23)
BAR = (22, 27, 34)
FG = (230, 237, 243)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
ACCENT = (255, 75, 75)

CASES = [
    ("自检", "tools/自检.py"),
    ("检索", "tools/演示_检索.py"),
    ("流水线", "test_mod4_执行引擎.py"),
]


def font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "consola.ttf"):
        p = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


F = font(17)
F_SMALL = font(14)
F_TITLE = font(15)


def wrap(draw, text: str, max_px: int) -> list:
    """按像素宽度折行（中文按字折，英文尽量按词）。"""
    out, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=F) > max_px:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return out or [""]


def color_of(line: str):
    if line.startswith("❌"):
        return RED
    if line.startswith("✅"):
        return GREEN
    if line.startswith("⚠"):
        return (210, 153, 34)
    if line.startswith(("$", ">", "#")):
        return ACCENT
    return FG


def render(lines, cmd: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 标题栏
    d.rectangle([0, 0, W, 38], fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([16 + i * 22, 14, 26 + i * 22, 24], fill=c)
    d.text((86, 10), "medipipe — 终端演示", font=F_TITLE, fill=DIM)
    # 命令行
    d.text((24, 52), "$ " + cmd, font=F, fill=ACCENT)
    # 输出
    y = 82
    for ln in lines:
        if y > H - 24:
            break
        mark, text = "", ln
        for emo, col in (("✅", GREEN), ("❌", RED), ("⚠️", (210, 153, 34)), ("⚠", (210, 153, 34))):
            if ln.startswith(emo):
                mark, text = emo, ln[len(emo):].lstrip()
                break
        if mark:
            dot = {"✅": GREEN, "❌": RED}.get(mark, (210, 153, 34))
            d.ellipse([24, y + 6, 34, y + 16], fill=dot)
            d.text((44, y), text, font=F, fill=FG)
        else:
            d.text((24, y), text, font=F, fill=color_of(ln))
        y += 22
    # 光标
    d.rectangle([24, y, 36, y + 16], fill=FG)
    return img


def build_gif(rows, cmd: str, out_path: Path, hold_ms: int = 2200):
    """rows 是「要显示的行」列表；每帧多显示一行。"""
    frames, durations = [], []
    # 第一帧放完整内容：这样在 GitHub/编辑器里不点开也能看到全貌
    frames.append(render(rows, cmd).convert("P", palette=Image.ADAPTIVE, colors=64))
    durations.append(1600)
    per = max(1, len(rows) // 26)          # 太长的输出一次多显示几行
    for i in range(1, len(rows) + 1, per):
        img = render(rows[:i], cmd)
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=64))
        durations.append(90)
    frames.append(render(rows, cmd).convert("P", palette=Image.ADAPTIVE, colors=64))
    durations.append(hold_ms)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    return out_path


def collect(repo: Path, script: str) -> tuple:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-u", script], cwd=str(repo),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=900)
    text = (p.stdout or "") + (p.stderr or "")
    lines = []
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if "missing ScriptRunContext" in raw:
            continue
        if raw.startswith(("Traceback", "  File \"", "    ")) and "Traceback" in text and p.returncode != 0:
            continue
        lines.extend(wrap(dummy, raw.rstrip(), W - 48))
    return lines[:34], p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", default=str(ROOT / "docs" / "gif"))
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out)

    for name, script in CASES:
        if not (repo / script).exists():
            print("跳过 %s：找不到 %s" % (name, script))
            continue
        lines, rc = collect(repo, script)
        if not lines:
            print("跳过 %s：没输出" % name)
            continue
        cmd = "python " + script.replace("/", "\\")
        p = build_gif(lines, cmd, out / ("%s.gif" % name))
        size = p.stat().st_size / 1024
        print("%-8s %3d 行输出 → %s（%.0f KB，rc=%d）" % (name, len(lines), p.name, size, rc))
    return 0


if __name__ == "__main__":
    sys.exit(main())

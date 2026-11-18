# -*- coding: utf-8 -*-
"""
一键自检：环境、依赖、数据、模型、Key、端口
=========================================================================
跑一遍就知道「哪里没准备好」，每条不合格的都给出下一步该敲什么命令。

用法
-------------------------------------------------------------------------
    python tools\\自检.py
    python tools\\自检.py --quiet     # 只打印问题

退出码：0 = 全部通过（允许有 ⚠️），1 = 有 ❌ 必须处理
=========================================================================
"""
import argparse
import importlib
import json
import os
import socket
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "records.db"
VEC = ROOT / "data" / "case_vectors.bin"
IDS = ROOT / "data" / "case_ids.jsonl"

OK, WARN, FAIL = "✅", "⚠️", "❌"
results = []


def add(level, title, detail="", fix=""):
    results.append((level, title, detail, fix))


def check_python():
    v = sys.version_info
    if v >= (3, 10):
        add(OK, "Python 版本", "%d.%d.%d" % (v[0], v[1], v[2]))
    else:
        add(FAIL, "Python 版本", "%d.%d.%d（需要 3.10+）" % (v[0], v[1], v[2]),
            "装 Python 3.10 或更高版本")


def check_deps():
    """依赖能不能导入；版本是否和 requirements.txt 一致。"""
    want = {}
    req = ROOT / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if "==" in line:
                pkg, ver = line.split("==", 1)
                want[pkg.strip()] = ver.strip()
    mods = {
        "streamlit": "streamlit", "streamlit_flow": "streamlit-flow-component",
        "pymupdf": "pymupdf", "dotenv": "python-dotenv", "requests": "requests",
        "bs4": "beautifulsoup4", "lxml": "lxml", "brotli": "brotli",
    }
    missing, mismatch = [], []
    for mod, pkg in mods.items():
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
            continue
        if pkg in want:
            try:
                from importlib.metadata import version

                if version(pkg) != want[pkg]:
                    mismatch.append("%s 装的是 %s，要求 %s" % (pkg, version(pkg), want[pkg]))
            except Exception:
                pass
    if missing:
        add(FAIL, "依赖", "缺：" + "、".join(missing), "pip install -r requirements.txt")
    elif mismatch:
        add(WARN, "依赖版本", "；".join(mismatch[:3]),
            "pip install -r requirements.txt（锁定版本）")
    else:
        add(OK, "依赖", "%d 个核心包都能导入" % len(mods))


def check_data():
    if not DB.exists():
        add(FAIL, "数据库", "没有 data/records.db",
            "python tools\\导入样例数据.py 然后 python tools\\导入开放数据.py")
        return
    conn = sqlite3.connect(str(DB), timeout=30)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {}
        for t in ("case_corpus", "drugs", "medquad_qa", "doid"):
            if t in tables:
                counts[t] = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        fts = 0
        if "search_fts" in tables:
            fts = conn.execute("SELECT COUNT(*) FROM search_fts").fetchone()[0]
    finally:
        conn.close()

    if not counts.get("case_corpus"):
        add(FAIL, "病例库", "case_corpus 是空的（或没有这张表）",
            "python tools\\导入样例数据.py")
    else:
        add(OK, "病例库", "%d 条" % counts["case_corpus"])

    if not counts.get("drugs"):
        add(WARN, "药品表", "drugs 是空的（或没有这张表）",
            "python tools\\导入开放数据.py")
    else:
        add(OK, "药品表", "%d 条" % counts["drugs"])

    extra = []
    if counts.get("medquad_qa"):
        extra.append("问答 %d" % counts["medquad_qa"])
    if counts.get("doid"):
        extra.append("疾病词表 %d" % counts["doid"])
    if extra:
        add(OK, "开放数据", "、".join(extra))

    if fts:
        add(OK, "全文索引", "%d 条" % fts)
    else:
        add(WARN, "全文索引", "还没有 search_fts（关键词检索会退回 LIKE，慢）",
            "python tools\\建搜索索引.py")


def check_vectors():
    if not (VEC.exists() and IDS.exists()):
        add(WARN, "向量库", "没有 case_vectors.bin / case_ids.jsonl（相似病例不可用）",
            "python tools\\建向量.py")
        return
    n = 0
    with open(IDS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    rows = VEC.stat().st_size // (1024 * 4)
    if rows < n:
        add(WARN, "向量库", "id %d 条，矩阵只装得下 %d 行" % (n, rows), "python tools\\建向量.py")
    else:
        add(OK, "向量库", "%d 条（1024 维）" % n)


def _ollama_tags(timeout=3.0):
    base = os.environ.get("FW_OLLAMA_BASE") or "http://127.0.0.1:11434"
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return None


def check_models():
    tags = _ollama_tags()
    if tags is None:
        add(WARN, "Ollama", "连不上（http://127.0.0.1:11434）",
            "装 Ollama 并启动：ollama serve")
        return
    add(OK, "Ollama", "在线，%d 个模型" % len(tags))
    need = {"bge-m3": "检索向量（相似病例必需）"}
    opt = {"qwen2.5:3b": "翻译首选", "qwen3-vl:4b": "读图 / 本地总结"}
    for name, why in need.items():
        hit = any(t.startswith(name) for t in tags)
        if hit:
            add(OK, "模型 " + name, why)
        else:
            add(FAIL, "模型 " + name, "没装（%s）" % why, "ollama pull " + name)
    for name, why in opt.items():
        if any(t.startswith(name) for t in tags):
            add(OK, "模型 " + name, why + "（可选）")
        else:
            add(WARN, "模型 " + name, "没装（%s，可选）" % why, "ollama pull " + name)


def check_key():
    try:
        from framework_b import b_配置

        k = b_配置.get_key()
    except Exception:
        k = ""
    if k:
        add(OK, "主模型 Key", b_配置.mask(k) if "b_配置" in dir() else "已配置")
    else:
        add(WARN, "主模型 Key", "没配（病历总结会退回本地模型，20~60 秒）",
            "在「自检」页填 Key，或 .env 里写 MY_LLM_KEY=sk-...")


def check_ports():
    for port in (8501, 8502):
        s = socket.socket()
        s.settimeout(0.5)
        busy = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if busy:
            add(OK, "端口 %d" % port, "已被占用（服务应该在跑）")
        else:
            add(WARN, "端口 %d" % port, "没人监听",
                "python -m streamlit run %s --server.port=%d"
                % ("app.py" if port == 8501 else "framework_b/app_b.py", port))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只打印问题")
    args = ap.parse_args()

    print("medipipe 自检")
    print("目录：%s" % ROOT)
    print("-" * 58)
    check_python()
    check_deps()
    check_data()
    check_vectors()
    check_models()
    check_key()
    check_ports()

    for level, title, detail, fix in results:
        if args.quiet and level == OK:
            continue
        line = "%s %-14s %s" % (level, title, detail)
        print(line)
        if fix and level != OK:
            print("   → " + fix)

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    print("-" * 58)
    print("通过 %d 项，提醒 %d 项，必须处理 %d 项"
          % (len(results) - len(fails) - len(warns), len(warns), len(fails)))
    if fails:
        print("结论：还不能完整用，先按上面的 → 处理")
        return 1
    print("结论：可以跑了" + ("（有 %d 项提醒，按需处理）" % len(warns) if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

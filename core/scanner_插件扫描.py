# -*- coding: utf-8 -*-
"""
插件 / 模型扫描器（scanner）
=========================================================================
目的：不要我把插件名字写死。**从你电脑里扫出来**，扫到什么就能选什么。

扫两类东西：
    1. 插件：指定目录下的 *.py，找出继承了 BasePlugin 的类
    2. 模型：Ollama 里已经拉下来的模型（bge-m3、qwen3-vl …）

怎么判断一个插件"要不要联网 / 要不要模型"？
-------------------------------------------------------------------------
不能靠猜，按三层来（可靠 → 备选）：

    第 1 层  看插件自己有没有声明 NEEDS
             NEEDS = {"network": True, "model": False, "files": False}

    第 2 层  没有声明就静态扫 import（不执行代码，安全）
             requests / httpx / aiohttp          → 联网
             openai / ollama / transformers      → 模型
             其余                                → 本地

    第 3 层  标到界面上（"插件（联网）"），你一眼能看出来
             敏感数据要不要走联网插件，就靠这个标签判断

为什么用 ast 而不是 import 进来？
-------------------------------------------------------------------------
import 会执行插件顶层代码（可能起服务、读文件、连数据库）。
扫描阶段只想知道"它长什么样"，所以用 ast 解析源码，零副作用。
=========================================================================
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根目录（本文件在 core/ 下）
ROOT = Path(__file__).resolve().parent.parent

#: 默认扫描目录（相对项目根）
DEFAULT_DIRS = ["plugins"]

# ---- 判断"这个插件碰不碰网络/模型"的关键词 ----
NETWORK_MODULES = {"requests", "httpx", "aiohttp", "urllib", "urllib3", "websockets", "socket", "http"}
MODEL_MODULES = {"openai", "ollama", "transformers", "sentence_transformers", "torch", "llama_cpp", "dashscope"}

#: 主模型节点是虚拟的（不落在文件里），单独加
VIRTUAL_ENTRIES = {
    "主模型": {"kind": "master", "key": "master", "tag": "主模型", "file": "", "needs": {}},
}


def _imports_of(tree: ast.AST) -> set:
    """收集一个模块里所有 import 的顶层包名。"""
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _class_attrs(cls: ast.ClassDef) -> Dict[str, Any]:
    """从类定义里抠出简单属性（name / NEEDS / desc）。"""
    out: Dict[str, Any] = {}
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            key = target.id
            value = node.value
            if isinstance(value, ast.Constant):
                out[key] = value.value
            elif key == "NEEDS" and isinstance(value, ast.Dict):
                # 只认 {"network": True, ...} 这种字面量
                parsed = {}
                for k, v in zip(value.keys, value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        parsed[str(k.value)] = bool(v.value)
                out[key] = parsed
    return out


def scan_file(path: Path) -> Optional[Dict[str, Any]]:
    """
    解析一个 .py，判断它是不是插件。是就返回描述信息，不是返回 None。

    返回：{key, file, name, tag, needs, desc}
    """
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return None

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    # 找"继承自 BasePlugin"的类
    plugin_cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            base_names = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
            if "BasePlugin" in base_names:
                plugin_cls = node
                break

    if plugin_cls is None:
        return None

    attrs = _class_attrs(plugin_cls)
    imports = _imports_of(tree)

    needs = attrs.get("NEEDS")
    if not isinstance(needs, dict):
        # 第 2 层：没有声明就用 import 判断
        #   除了第三方库，本项目自己的 core.llm（MasterLLM）也算"要用模型"
        #   * core.llm / MasterLLM   → 自己 import 了主模型
        #   * ctx 里取 master        → 从上下文拿主模型（分类插件就是这样）
        uses_own_llm = (
            ("MasterLLM" in src)
            or ("core.llm_主模型" in src)
            or ('"master"' in src)
        )
        needs = {
            "network": bool(imports & NETWORK_MODULES),
            "model": bool(imports & MODEL_MODULES) or uses_own_llm,
        }

    if needs.get("network"):
        tag = "插件（联网）"
    elif needs.get("model"):
        tag = "插件（模型）"
    else:
        tag = "插件（本地）"

    # 描述：取类 docstring 或模块 docstring 的第一行有用的话
    desc = ""
    doc = ast.get_docstring(plugin_cls) or ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line and not line.startswith("=") and len(line) > 4:
            desc = line[:40]
            break

    name = str(attrs.get("name") or plugin_cls.name)

    # 文件名是「英文_中文.py」时，key 只取英文部分：
    #   web_scraper_网页抓取.py → key=web_scraper
    # 这样执行 JSON 里是干净的英文步骤名，文件名又能一眼看懂。
    key = path.stem
    if "_" in key:
        head, _, tail = key.rpartition("_")
        if head and any("\u4e00" <= ch <= "\u9fa5" for ch in tail):
            key = head

    return {
        "key": key,
        "file": str(path),
        "name": name,
        "tag": tag,
        "needs": needs,
        "desc": desc,
    }


def scan_plugins(extra_dirs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    扫描插件目录，返回可用的插件列表。

    extra_dirs 里可以放绝对路径（你自己代码所在的文件夹）。
    """
    found: List[Dict[str, Any]] = []
    # 按**文件路径**去重（同一个文件被扫到两次才跳过）。
    # 以前按 key（文件名）去重，两个不同目录下的 same_name.py 会被当成
    # 同一个插件，第二个静默丢失 —— 这是个真 bug。
    seen_paths = set()

    dirs: List[Path] = [ROOT / d for d in DEFAULT_DIRS]
    for extra in (extra_dirs or []):
        p = Path(extra)
        if p.exists():
            dirs.append(p)

    for d in dirs:
        if not d.exists():
            continue
        # 递归进子文件夹：插件可能被你放在 plugins/xxx/ 里
        for info in scan_dir_recursive(d, max_files=400):
            real = str(Path(info["file"]).resolve())
            if real in seen_paths:
                continue
            seen_paths.add(real)

            # 文件名撞了 → 加后缀，保证 key 唯一（执行引擎靠 key 找实例）
            base_key = info["key"]
            used = {f["key"] for f in found}
            if base_key in used:
                i = 2
                while "%s_%d" % (base_key, i) in used:
                    i += 1
                info["key"] = "%s_%d" % (base_key, i)

            info["from"] = str(d)
            found.append(info)

    return found


#: 全盘扫描时直接跳过的目录（扫了也没用，还特别慢）
SKIP_DIR_NAMES = {
    "node_modules", ".git", ".svn", "__pycache__", "venv", ".venv", "env",
    "site-packages", "dist-info", "AppData", "ProgramData", "Windows",
    "Program Files", "Program Files (x86)", "System Volume Information",
    "$Recycle.Bin", "Recovery", "PerfLogs", "msys64", "Cygwin",
    ".cache", ".conda", "pkgs", "packages", "Lib", "libs",
    # 这些是"别人的大项目"，扫进去只会把名额吃光（踩过坑）
    "ComfyUI", "GPT-SoVITS", "CosyVoice", "stable-diffusion-webui", "SD", "NapCat", "ollama",
}


def scan_dir_recursive(
    root: Path,
    max_files: int = 400,
    max_seconds: float = 15.0,
    max_depth: int = 6,
    stats: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    扫一个目录（含子文件夹），把插件找出来。

    ⚠️ 为什么是"广度优先"而不是 os.walk 那种深度优先？
        踩过坑：先扫 D:\\干活区，结果一路钻进 ComfyUI，把 800 个
        .py 名额全用光了，你自己的插件一个都没轮到。
        改成逐层往下（浅的先扫），并且限制最大深度，
        这样"你自己写的代码"总能排在前面。

    三个上限（防止扫一整天）：max_files / max_seconds / max_depth
    到上限就返回已找到的部分，统计信息会写进 stats（页面上提示"可能不全"）。
    """
    import time
    from collections import deque

    start = time.time()
    found: List[Dict[str, Any]] = []
    checked = 0
    queue = deque([(root, 0)])
    visited_dirs = 0

    while queue:
        if checked >= max_files or (time.time() - start) > max_seconds:
            break

        cur, depth = queue.popleft()
        visited_dirs += 1

        try:
            entries = list(os.scandir(cur))
        except Exception:
            continue

        for e in entries:
            try:
                if e.is_dir():
                    name = e.name
                    if depth >= max_depth:
                        continue
                    if name in SKIP_DIR_NAMES or name.startswith("."):
                        continue
                    queue.append((Path(e.path), depth + 1))
                    continue

                if not e.name.endswith(".py"):
                    continue
                if e.name in ("base.py", "__init__.py") or e.name.startswith("_"):
                    continue
                if checked >= max_files or (time.time() - start) > max_seconds:
                    break

                checked += 1
                if e.stat().st_size > 400_000:     # 插件不会这么大
                    continue

                info = scan_file(Path(e.path))
                if info:
                    found.append(info)
            except Exception:
                continue

    if stats is not None:
        stats.update(
            {
                "checked": checked,
                "dirs": visited_dirs,
                "seconds": round(time.time() - start, 1),
                "truncated": checked >= max_files or (time.time() - start) > max_seconds,
            }
        )
    return found


def scan_full_disk(
    max_seconds: float = 25.0,
    max_files: int = 3000,
    max_depth: int = 5,
) -> Dict[str, Any]:
    """
    扫整台电脑（所有盘符）找插件。

    ⚠️ 结果一定**不全**，页面上必须告诉用户：
        * 有时间和文件数上限（不然要扫几十分钟）
        * 跳过了 Windows / AppData / node_modules / ComfyUI 这类目录
        * 只认"继承 BasePlugin 的类"

    返回 {"found": [...], "checked": n, "seconds": s, "truncated": bool}
    """
    import string
    import time

    start = time.time()
    found: List[Dict[str, Any]] = []
    total_checked = 0
    truncated = False

    # 盘符顺序：先扫非 C 盘（你自己的东西一般不在系统盘），C 盘放最后
    letters = list(string.ascii_uppercase)
    drives = ["%s:\\" % L for L in letters if os.path.exists("%s:\\" % L)]
    drives.sort(key=lambda d: (d.upper().startswith("C:"), d))

    for drive in drives:
        if (time.time() - start) > max_seconds:
            truncated = True
            break
        remaining = max(1.0, max_seconds - (time.time() - start))
        stats: Dict[str, Any] = {}
        found.extend(
            scan_dir_recursive(
                Path(drive),
                max_files=max(50, max_files // max(1, len(drives))),
                max_seconds=remaining,
                max_depth=max_depth,
                stats=stats,
            )
        )
        total_checked += int(stats.get("checked", 0))
        if stats.get("truncated"):
            truncated = True

    # 按文件路径去重；不同路径但同 key 的插件保留，并给 key 加后缀。
    # 不能只按 key 去重，否则两个不同目录下的同名插件会被静默丢掉。
    seen_paths = set()
    used_keys = set()
    unique = []
    for f in found:
        real = str(Path(f["file"]).resolve())
        if real in seen_paths:
            continue
        seen_paths.add(real)
        base = f["key"]
        key = base
        i = 2
        while key in used_keys:
            key = "%s_%d" % (base, i)
            i += 1
        f["key"] = key
        used_keys.add(key)
        unique.append(f)

    return {
        "found": unique,
        "checked": total_checked,
        "seconds": round(time.time() - start, 1),
        "truncated": truncated,
    }


def scan_ollama_models(base: str = "http://127.0.0.1:11434") -> List[Dict[str, Any]]:
    """
    列出 Ollama 里已下载的模型。返回 [{key, name, tag, model}]。

    服务没起来不报错，返回空列表（页面上会提示"Ollama 没开"）。
    """
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []

    out = []
    for m in data.get("models", []):
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        short = name.split(":")[0]
        # 显示名：短、能认。取名字前 4 个字符
        out.append(
            {
                "key": name,
                "name": short[:6],
                "tag": "轻量模型",
                "model": name,
                "size_gb": round(float(m.get("size") or 0) / 1024 ** 3, 2),
            }
        )
    return out


def _scan_ollama_from_disk(stores: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    直接从磁盘读 Ollama 的模型清单（**不需要服务在跑**）。

    Ollama 把模型登记在 manifests 目录里，结构是：
        <store>\\manifests\\registry.ollama.ai\\library\\<模型名>\\<标签>
    每个文件是一段 JSON，里面 layers 记录了各层大小，加起来就是模型大小。

    之前只调 /api/tags，Ollama 一关就什么都扫不到 —— 所以补了这条路径。
    """
    import json

    if stores:
        roots = stores
    else:
        try:
            from config_配置 import OLLAMA_STORES  # type: ignore

            roots = OLLAMA_STORES
        except Exception:
            roots = [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\models"),
                r"D:\ollama\ollamaiamgers",
            ]

    found: List[Dict[str, Any]] = []
    seen = set()

    for root in roots:
        root = os.path.expandvars(root)
        manifests = Path(root) / "manifests"
        if not manifests.exists():
            continue

        for dirpath, _dirnames, filenames in os.walk(manifests):
            for name in filenames:
                # .../library/bge-m3/latest  →  模型 bge-m3，标签 latest
                model_dir = Path(dirpath).name
                tag = name
                if model_dir in ("library", "manifests"):
                    continue                    # 层级不对，跳过
                key = "%s:%s" % (model_dir, tag)
                if key in seen:
                    continue
                seen.add(key)

                size_gb = 0.0
                try:
                    with open(Path(dirpath) / name, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    layers = data.get("layers") or []
                    total = sum(int(layer.get("size") or 0) for layer in layers if isinstance(layer, dict))
                    size_gb = round(total / 1024 ** 3, 2)
                except Exception:
                    pass

                found.append(
                    {
                        "key": key,
                        "name": model_dir[:8],
                        "tag": "轻量模型",
                        "model": key,
                        "source": "ollama",
                        "size_gb": size_gb,
                    }
                )
    return found


def _scan_hf_cache() -> List[Dict[str, Any]]:
    """扫 HuggingFace 缓存（模型名在目录名里：models--org--name）。"""
    home = os.path.expanduser("~")
    # 只认 HuggingFace 的 hub 目录：里面每个模型都叫 models--组织--名字
    # （别把 D:\\hf-sd15-config 这种"配置目录"当成模型，里面全是 scheduler/vae 这种零件）
    roots = [Path(home) / ".cache" / "huggingface" / "hub"]
    found = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                name = d.name
                if not name.startswith("models--"):
                    continue                     # 不是模型目录，跳过
                parts = name.split("--")
                name = parts[-1] if len(parts) >= 2 else name   # 只取模型名，不带组织名
                found.append(
                    {
                        "key": str(d),
                        "name": name[:10],
                        "tag": "轻量模型",
                        "model": str(d),
                        "source": "huggingface",
                        "size_gb": 0.0,
                    }
                )
        except Exception:
            continue
    return found


def _scan_model_files(dirs: Optional[List[str]] = None, max_files: int = 60) -> List[Dict[str, Any]]:
    """找散落的模型文件（.gguf / .safetensors），只在这些常见目录里找。"""
    if dirs:
        roots = dirs
    else:
        try:
            from config_配置 import MODEL_DIRS  # type: ignore

            roots = MODEL_DIRS
        except Exception:
            roots = [r"D:\干活区\ComfyUI\models", os.path.expanduser("~/models")]
    exts = {".gguf", ".safetensors", ".onnx"}
    found = []
    count = 0
    for root in roots:
        p = Path(os.path.expandvars(root))
        if not p.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(p):
            for name in filenames:
                if count >= max_files:
                    return found
                if Path(name).suffix.lower() not in exts:
                    continue
                count += 1
                f = Path(dirpath) / name
                try:
                    size_gb = round(f.stat().st_size / 1024 ** 3, 2)
                except Exception:
                    size_gb = 0.0
                if size_gb < 0.05:      # 太小的多半是配置/占位文件
                    continue
                found.append(
                    {
                        "key": str(f),
                        "name": Path(name).stem[:10],
                        "tag": "轻量模型",
                        "model": str(f),
                        "source": "file",
                        "size_gb": size_gb,
                    }
                )
    return found


def scan_models(deep: bool = False) -> List[Dict[str, Any]]:
    """
    扫本地模型：Ollama（磁盘）+ HuggingFace 缓存 + 模型文件。

    deep=False  只扫清单（很快，进页面就能跑）
    deep=True   连 .gguf / .safetensors 文件也翻（慢一点，按需点按钮）
    """
    models: List[Dict[str, Any]] = []
    models.extend(scan_ollama_models())       # 服务在跑就优先用 API（信息最准）
    models.extend(_scan_ollama_from_disk())   # 服务没跑就从磁盘读
    models.extend(_scan_hf_cache())
    if deep:
        models.extend(_scan_model_files())

    # 按 key 去重
    seen = set()
    unique = []
    for m in models:
        if m["key"] in seen:
            continue
        seen.add(m["key"])
        unique.append(m)
    return unique


def build_catalog(extra_dirs: Optional[List[str]] = None, with_models: bool = True,
                  extra_plugins: Optional[List[Dict[str, Any]]] = None,
                  deep_models: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    组装页面用的"可选清单"：插件 + 模型 + 主模型。

    返回：{显示名: {kind, key, tag, file/model, desc}}
    显示名 = 插件自己声明的 name（没有就用文件名），重名时加后缀。
    """
    catalog: Dict[str, Dict[str, Any]] = {}

    def put(label: str, meta: Dict[str, Any]) -> None:
        # 重名加序号，避免选不到
        if label in catalog:
            i = 2
            while "%s%d" % (label, i) in catalog:
                i += 1
            label = "%s%d" % (label, i)
        catalog[label] = meta

    # 主模型（虚拟节点，永远有）
    for label, meta in VIRTUAL_ENTRIES.items():
        put(label, meta)

    # 插件（目录扫描 + 全盘扫描的结果）
    plugins = scan_plugins(extra_dirs) + list(extra_plugins or [])
    for p in plugins:
        put(
            p["name"],
            {
                "kind": "plugin",
                "key": p["key"],
                "tag": p["tag"],
                "file": p["file"],
                "needs": p["needs"],
                "desc": p["desc"],
            },
        )

    # 本地模型（默认扫：磁盘读取很快，不再依赖 Ollama 服务）
    if with_models:
        for m in scan_models(deep=deep_models):
            put(
                m["name"],
                {
                    "kind": "model",
                    "key": m["key"],
                    "tag": m.get("tag", "轻量模型"),
                    "model": m.get("model", m["key"]),
                    "source": m.get("source", ""),
                    "size_gb": m.get("size_gb", 0),
                },
            )

    return catalog


# -------------------------------------------------------------------------
# 自测：python core/scanner_插件扫描.py
# -------------------------------------------------------------------------
if __name__ == "__main__":
    print("扫描插件目录：")
    for p in scan_plugins():
        print("  %-14s %-12s needs=%s" % (p["name"], p["tag"], p["needs"]))
        print("     文件：%s" % os.path.basename(p["file"]))

    print("\nOllama 模型：")
    models = scan_ollama_models()
    if models:
        for m in models:
            print("  %-10s %-12s %.2f GB" % (m["name"], m["tag"], m["size_gb"]))
    else:
        print("（Ollama 没开，或者没装模型）")

    print("\n最终清单：")
    for label, meta in build_catalog().items():
        print("  %-10s %s" % (label, meta["tag"]))

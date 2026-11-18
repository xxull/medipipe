# -*- coding: utf-8 -*-
"""
PDF 取文插件（pdf_text）
=========================================================================
从 PDF 里提取文字。给"财报、年报、公告"这类只有 PDF 的数据源用。

两种用法
-------------------------------------------------------------------------
    * 输入一个**本地文件路径**  → 直接读那个 PDF
    * 输入一个**网址**          → 先下载，再读
    （网址以 .pdf 结尾，或返回的内容是 PDF 时，就按 PDF 处理）

为什么要单独一个插件？
-------------------------------------------------------------------------
框架本身只管"按图执行"，不知道什么是 PDF。
抓网页用 web_scraper，抓 PDF 就用这个 —— 需要什么能力就装什么插件。

限制（先说清楚，免得你踩坑）
-------------------------------------------------------------------------
    * 只能取**文字层**。扫描件（图片版 PDF）取出来是空的，那需要 OCR。
    * 加了页数上限（默认 80 页），年报几百页的只取前几十页。
    * 下载有超时（默认 60 秒）。
=========================================================================
"""

from __future__ import annotations

import os
import re

from base_基类 import BasePlugin
from core.url_safety import UnsafeURLError, assert_public_http_url

#: 最多读多少页
MAX_PAGES = 80

#: 下载超时（秒）
TIMEOUT = 60


class PDFText(BasePlugin):
    """把 PDF 转成纯文本。"""

    name = "PDF取文"
    NEEDS = {"network": True, "model": False}
    OUTPUT_FIELDS = ["text"]

    def execute(self, text_data: str) -> str:
        target = (text_data or "").strip()
        if not target:
            raise RuntimeError("PDF 插件需要文件路径或网址，但收到的是空的")

        if re.match(r"^https?://", target, re.I):
            data = self._download(target)
            title = target
        else:
            path = target.strip('"').strip("'")
            if not os.path.exists(path):
                raise RuntimeError("找不到这个文件：%s" % path)
            with open(path, "rb") as fp:
                data = fp.read()
            title = os.path.basename(path)

        text = self._extract(data, title_hint=title)
        if not text.strip():
            raise RuntimeError(
                "这个 PDF 里没有文字层（可能是扫描件/图片版）。"
                "需要的话得加一个 OCR 插件，比如 RapidOCR。"
            )
        return text

    # ------------------------------------------------------------------
    @staticmethod
    def _download(url: str) -> bytes:
        """下载 PDF 到内存。"""
        import requests

        try:
            assert_public_http_url(url)
        except UnsafeURLError as exc:
            raise RuntimeError(str(exc)) from exc

        try:
            r = requests.get(
                url,
                timeout=TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"},
            )
            r.raise_for_status()
        except Exception as exc:
            raise RuntimeError("下载 PDF 失败：%s" % exc)

        head = r.content[:5]
        if head[:4] != b"%PDF":
            raise RuntimeError(
                "这个网址返回的不是 PDF（可能是登录页/跳转页）。"
                "可以先抓网页，或者换直接指向 .pdf 的链接"
            )
        return r.content

    @staticmethod
    def _extract(data: bytes, title_hint: str = "") -> str:
        """从 PDF 字节里抽文字。"""
        try:
            import pymupdf  # 新版包名
        except Exception:
            try:
                import fitz as pymupdf  # 老版包名
            except Exception:
                raise RuntimeError("没装 PyMuPDF：pip install pymupdf")

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise RuntimeError("这个 PDF 打不开（可能损坏或加密）：%s" % exc)

        pages = []
        total = min(len(doc), MAX_PAGES)
        for i in range(total):
            try:
                pages.append(doc[i].get_text("text"))
            except Exception:
                continue
        doc.close()

        body = "\n".join(pages)
        # 收拾一下：连续空行压成一个，去掉行尾空格
        body = re.sub(r"[ \t]+\n", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body)

        header = "标题：%s\n来源：PDF（共 %d 页，读取前 %d 页）\n\n" % (title_hint, len(pages), total)
        return header + body.strip()


# -------------------------------------------------------------------------
# 自测：python plugins/pdf_text_PDF取文.py <文件或网址>
# -------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not arg:
        print("用法：python plugins/pdf_text_PDF取文.py <本地pdf路径 或 网址>")
        sys.exit(0)
    p = PDFText()
    try:
        out = p.execute(arg)
        print(out[:600])
        print("\n……共 %d 字" % len(out))
    except Exception as exc:
        print("失败：", exc)

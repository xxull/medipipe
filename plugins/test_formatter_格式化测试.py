# -*- coding: utf-8 -*-
"""
测试插件 2：HTML 段落包装
=========================================================================
作用：在文本前后加上 <p> 和 </p>。

这是通用示例：把一段纯文本包装成 HTML 段落，后面可由渲染插件统一排版。
=========================================================================
"""

from __future__ import annotations

from base_基类 import BasePlugin


class TestFormatter(BasePlugin):
    """把文本包成 <p>...</p>。"""

    name = "test_formatter"

    def execute(self, text_data: str) -> str:
        # 简单包装：不做转义。真实项目里应该先 html.escape，防止注入
        return "<p>" + text_data + "</p>"

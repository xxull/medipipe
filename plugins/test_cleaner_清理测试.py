# -*- coding: utf-8 -*-
"""
测试插件 1：文本清洗
=========================================================================
作用：把输入文本里的所有空白字符（空格、全角空格、制表符、换行）全部去掉。

这是通用示例：把 PDF/OCR 抓下来的文本先压平，后续正则/实体识别更容易处理。
=========================================================================
"""

from __future__ import annotations

import re

from base_基类 import BasePlugin


class TestCleaner(BasePlugin):
    """去掉所有空白字符。"""

    name = "test_cleaner"

    def execute(self, text_data: str) -> str:
        # \s 在 Python 里默认匹配：空格、\t、\n、\r、\f、\v
        # 中文全角空格（\u3000）不算在 \s 里，所以要单独处理
        text = re.sub(r"[\s\u3000]+", "", text_data)
        return text

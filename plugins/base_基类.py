# -*- coding: utf-8 -*-
"""
插件基类
=========================================================================
所有放在 plugins/ 下的插件都必须继承 BasePlugin，并实现 execute()。

为什么要统一基类？
  * 内核能靠 isinstance 判断“这个类是不是插件”，避免把普通类当插件加载；
  * 强制约定 execute(self, text_data) -> str 这个接口签名；
  * 以后要加统一能力（比如 before/after 钩子、超时、重试），
    只改基类一处，所有插件自动具备。
=========================================================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BasePlugin(ABC):
    """数据流水线里所有插件的父类。"""

    #: 插件名称，默认用类名；子类可以覆盖成更友好的中文名
    name: str = ""

    def __init__(self) -> None:
        # 如果子类没写 name，就退化成类名，保证日志里永远有名字可打
        if not self.name:
            self.name = self.__class__.__name__

    @abstractmethod
    def execute(self, text_data: str) -> str:
        """
        处理输入文本，返回处理后的文本。

        参数
        ----
        text_data : 上一步的输出（第一步时是用户原始输入）

        返回
        ----
        新的文本；**必须是 str**，返回 None 或其它类型会被内核判定为错误。

        约定
        ----
        * 不要修改入参，返回新字符串（便于排查“到底哪一步改坏了”）；
        * 不要在插件里吞异常——抛出来，内核会打红字并中断流水线。
        """
        raise NotImplementedError

    def __repr__(self) -> str:  # 方便调试时直接 print(plugin)
        return "<%s name=%r>" % (self.__class__.__name__, self.name)

    # ---------------------------------------------------------------------
    # 可选：给"多 AI 调度器"用的富接口
    # ---------------------------------------------------------------------
    # run_pipeline.py 那种简单串行只用 execute(text) -> str。
    # 但多 AI 调度需要结构化输入输出（比如抽取插件要返回 dict），
    # 所以这里给一个默认实现：把 execute 的结果包成 {"text": ...}。
    # 需要结构化能力的插件，自己覆盖 execute_rich 即可，内核不用改。
    def execute_rich(self, ctx: dict) -> dict:
        """结构化执行入口。默认把 ctx["text"] 交给 execute()，包一层返回。"""
        text = ctx.get("text", "")
        return {"text": self.execute(text)}

# -*- coding: utf-8 -*-
"""
插件：网页抓取（web_scraper）
=========================================================================
输入：一个网址（或含网址的一小段文字）
输出：网页正文（只取 <p> 段落，压平空白，最多 3000 字）

为什么只取 <p>？
-------------------------------------------------------------------------
资讯页面的导航、版权、评论、脚本里全是噪音。
只提 <p> 正文是最省事、效果也不差的过滤方式：
    * 正文段落几乎一定在 <p> 里；
    * 导航通常是 <a>/<li>，评论是 div+span，脚本是 <script>。
如果某站正文不是 <p>（比如 div 堆出来的），本插件会返回空，
这时应该换更精细的抓取策略，而不是把整页 HTML 丢给大模型烧 token。

三个关键防护（对应需求）
-------------------------------------------------------------------------
1. 反爬 headers：UA / Accept / Accept-Language / Referer 都伪装成正常浏览器；
2. 3000 字硬截断：防止一篇长文章把后续所有步骤的 token 预算吃光；
3. 10 秒 watchdog：requests 自己的 timeout 只管“连接/读取单次阻塞”，
   遇到服务端慢慢吐字节（slowloris）会一直挂着。
   所以外面再套一层“总时限”线程池，到点直接放弃，绝不让流水线卡死。
=========================================================================
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from base_基类 import BasePlugin
from core.url_safety import UnsafeURLError, assert_public_http_url

# -------------------------------------------------------------------------
# 反爬 headers：模仿 Windows 上的 Chrome，中文站点建议带 Accept-Language
# -------------------------------------------------------------------------
# ⚠️ 这里故意**不写 Accept-Encoding**。
# 踩过的坑：手写了 "gzip, deflate, br" 之后，服务器会真的返回 brotli 压缩流；
# 如果环境里没装 brotli，requests 解不开，resp.content 是一堆二进制乱码，
# BeautifulSoup 自然一个 <p> 都找不到，最后报“没解析出正文”，极难排查。
# 交给 requests/urllib3 自己协商：装了 brotli 它就带上 br，没装就只要 gzip。
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# 总时限（秒）：超过就直接放弃，不等它慢慢吐
WATCHDOG_SECONDS = 10
# 连接/读取单次超时（秒）：比总时限短，正常情况下它先生效
REQUEST_TIMEOUT = (5, 8)
# 正文上限（字）：防 token 爆炸
MAX_CHARS = 3000


class WebScrapeError(Exception):
    """抓取过程中的中文异常（内核会红字打印并中断流水线）。"""


def _extract_url(text: str) -> str:
    """
    从输入里找出第一个网址。

    允许的输入形态：
        "https://example.com/a"
        "帮我抓一下 https://example.com/a 的内容"
        "example.com/a"          （自动补 https://）
    """
    raw = str(text or "").strip()
    if not raw:
        raise WebScrapeError("输入为空，需要一个网址")

    # 先挡掉危险/不支持的协议。
    # 必须在“猜域名”之前做：否则 "file:///C:/Windows/win.ini" 会被下面
    # 的域名正则抓出 "win.ini"，再被当成 https 去解析，报一个莫名其妙的 DNS 错误。
    bad = re.search(r"\b(file|ftp|gopher|javascript|data)\s*:\s*", raw, re.I)
    if bad:
        raise WebScrapeError("只支持 http/https 网址，不支持 %s 协议" % bad.group(1).lower())

    # 再按“带协议”的正则找
    m = re.search(r"https?://[^\s\u4e00-\u9fff，。；、）】\"'<>]+", raw)
    if m:
        return m.group(0).rstrip(".,;)]}")

    # 再按“像域名”的形态找，自动补 https
    m = re.search(r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s\u4e00-\u9fff]*)?", raw)
    if m:
        return "https://" + m.group(0).rstrip(".,;)]}")

    raise WebScrapeError("没找到网址。请直接给一个链接，例如 https://example.com/news/123")


def _normalize_encoding(resp: requests.Response) -> str:
    """
    纠正编码，避免中文乱码。

    requests 依赖响应头里的 charset；国内不少站点返回 GBK 但头里写 ISO-8859-1，
    这时按 apparent_encoding（chardet 猜的）来取文本更可靠。
    """
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "charset=" in ctype:
        return resp.text

    guessed = resp.apparent_encoding or "utf-8"
    # apparent_encoding 有时猜成 ascii，那是纯英文页，无所谓
    try:
        return resp.content.decode(guessed, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return resp.content.decode("utf-8", errors="replace")


def _clean_text(html: str) -> str:
    """
    从 HTML 里抽正文并压平空白。

    三层过滤（只靠“只取 <p>”是不够的 —— 人民网这类站点，页脚的备案号、
    举报电话、友情链接链接全在 <p> 里，会把正文挤掉一大半）：

      1. 先拆掉结构噪音：footer/nav/header/aside，以及 class/id 里带
         footer、nav、sidebar、comment、ad、breadcrumb 的容器；
      2. 只取 <p>，压平空白（含全角空格），丢掉 <8 字的碎片；
      3. 按内容再筛一遍：命中页脚特征词（备案、举报电话、Copyright…）的丢掉；
         再把“像链接列表”的丢掉（没有一句中文标点，却有一堆分隔符）。

    如果第 3 层把内容筛空了（比如某站正文写得特别碎），就退回第 2 层的结果，
    宁可多留一点，也不能返回空。
    """
    soup = BeautifulSoup(html, "html.parser")

    # ---- 第 1 层：结构噪音 ----
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    noise_tags = ["footer", "nav", "header", "aside"]
    for name in noise_tags:
        for tag in soup.find_all(name):
            tag.decompose()

    noise_pattern = re.compile(
        r"(footer|navbar|nav-|nav_|sidebar|side-bar|comment|breadcrumb|"
        r"advert|ad-banner|copyright|friendlink|link-list)",
        re.I,
    )
    # 先快照成列表再删。
    # 直接边遍历 find_all(True) 边 decompose() 有个坑：
    # 删掉父节点后，原本在列表里的子节点会被拆空，tag.get(...) 直接抛
    # 'NoneType' object has no attribute 'get'。所以这里先固化列表，再逐个判断。
    for tag in list(soup.find_all(True)):
        if tag is None or getattr(tag, "parent", None) is None:
            continue  # 已经被父节点连带删掉了
        try:
            classes = " ".join(tag.get("class") or [])
            attrs = " ".join(filter(None, [classes, tag.get("id") or ""]))
        except Exception:
            continue
        if attrs and noise_pattern.search(attrs):
            tag.decompose()

    # ---- 第 2 层：只取 <p>，压平空白 ----
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        text = re.sub(r"[\s\u3000]+", " ", text).strip()
        if len(text) < 8:
            continue
        paragraphs.append(text)

    # ---- 第 3 层：按内容筛 ----
    footer_words = re.compile(
        r"(备案|ICP备|举报电话|举报邮箱|版权所有|copyright|all rights reserved|"
        r"许可证|营业执照|增值电信|服务邮箱|联系我们|关于我们|广告服务|"
        r"友情链接|无障碍|隐私政策|用户协议)",
        re.I,
    )
    # 判“像链接列表”：没有任何中文句读，却出现多个竖线/顿号分隔
    sentence_punct = re.compile(r"[，。！？；：,.!?;:]")

    def is_content(text: str) -> bool:
        if footer_words.search(text):
            return False
        # 长段落一般是正文，不因为标点少就丢掉
        if len(text) >= 60:
            return True
        return bool(sentence_punct.search(text))

    filtered = [t for t in paragraphs if is_content(t)]
    # 筛太狠就退回上一层（保证不空）
    chosen = filtered if filtered else paragraphs

    # ---- 第 4 层：兜底 ----
    # 有些站点正文根本不放在 <p> 里（div/span 堆出来的），
    # 这时候 <p> 一个都抓不到，直接返回空会让整条链路断在这里。
    # ⚠️ 必须用**原始 HTML 重新解析**再兜底：上面的噪声过滤可能把正文容器
    # 一起删掉了（class 里带 nav 之类），在删过的 soup 上兜底会返回空。
    if not chosen:
        fresh = BeautifulSoup(html, "html.parser")
        for tag in fresh(["script", "style", "noscript", "svg", "iframe", "form"]):
            tag.decompose()
        raw_blocks = _fallback_blocks(fresh)
        # 兜底也要讲质量：只留"像句子"的块（有句读，或者够长）。
        # 否则抓回来一堆 "Beginner's Guide, Programmers" 这种导航文字，
        # 入库后看着有数据，其实全是垃圾，比空更糟。
        def looks_sentence(b: str) -> bool:
            return len(b) >= 60 or bool(re.search(r"[，。！？；：,.!?;:]", b))

        chosen = [b for b in raw_blocks if looks_sentence(b)]

    return "\n".join(chosen)


def _fallback_blocks(soup) -> list:
    """
    <p> 抓不到时的兜底：从 article / main / body 里按块取文字。

    只取"看起来像段落"的块（长度 >= 20），避免把整页导航文字扫进来。
    """
    for selector in ("article", "main", "[role=main]", "div.content", "div#content"):
        container = soup.select_one(selector)
        if container is not None:
            blocks = _blocks_from(container)
            if blocks:
                return blocks

    blocks = _blocks_from(soup.body or soup)
    if blocks:
        return blocks

    # 最后一道：直接把整块文字按行切开，留像样的行
    # （有些站点的结构实在没有可用的块级容器）
    raw = (soup.body or soup).get_text("\n", strip=True)
    out = []
    for line in raw.splitlines():
        line = re.sub(r"[\s\u3000]+", " ", line).strip()
        if len(line) >= 20 and line not in out:
            out.append(line)
    return out[:80]


def _blocks_from(node) -> list:
    """按 div/li/td 这些块级元素收集文字，能出正文的最小粒度。"""
    out = []
    for tag in node.find_all(["div", "li", "td", "section", "blockquote", "span"]):
        # 只取"直接装着文字"的块，避免整块父容器重复收一遍
        if tag.find(True) is not None and len(tag.find_all(True)) > 3:
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        text = re.sub(r"[\s\u3000]+", " ", text).strip()
        if len(text) >= 20 and text not in out:
            out.append(text)
    return out


def _fetch(url: str) -> str:
    """真正发请求的地方（会被 watchdog 包一层）。"""
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.exceptions.SSLError:
        # 证书有问题时默认不放行；确实要访问证书链不全的站点，
        # 显式设置 FW_ALLOW_INSECURE_TLS=1 再降级重试。
        if os.environ.get("FW_ALLOW_INSECURE_TLS") != "1":
            raise WebScrapeError("证书验证失败；如确认站点可信，设置 FW_ALLOW_INSECURE_TLS=1 后重试")
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT, verify=False)  # noqa: S501
    except requests.exceptions.ConnectionError as exc:
        raise WebScrapeError("连不上这个网站（网络不通或被墙）：%s" % exc) from exc
    except requests.exceptions.Timeout as exc:
        raise WebScrapeError("请求超时（%d 秒内没响应）" % WATCHDOG_SECONDS) from exc
    except requests.exceptions.RequestException as exc:
        raise WebScrapeError("请求失败：%s" % exc) from exc

    if resp.status_code == 403:
        raise WebScrapeError("被网站拒绝访问（403），可能需要登录或有反爬策略")
    if resp.status_code == 404:
        raise WebScrapeError("页面不存在（404）")
    if resp.status_code >= 400:
        raise WebScrapeError("网站返回错误状态码：%d" % resp.status_code)

    return _normalize_encoding(resp)


class WebScraper(BasePlugin):
    """把网页正文抓下来，作为后续步骤的输入。"""

    name = "网页抓取"

    def execute(self, text_data: str) -> str:
        url = _extract_url(text_data)

        # 只允许 http/https，挡掉 file:// / ftp:// 这类本地文件读取
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise WebScrapeError("只支持 http/https 网址，收到的是：%s" % scheme)
        try:
            assert_public_http_url(url)
        except UnsafeURLError as exc:
            raise WebScrapeError(str(exc)) from exc

        started = time.perf_counter()

        # ---- watchdog：把抓取丢进线程，最多等 10 秒 ----
        # 说明：Python 没法真正杀死一个卡在 socket 上的线程，
        # 但主流程可以"不等它了"，继续走异常分支 —— 对流水线来说这就够了。
        #
        # ⚠️ 踩过的坑：不要用 `with ThreadPoolExecutor(...) as pool:`。
        # with 退出时会调用 shutdown(wait=True)，等于**等那个线程跑完**，
        # 结果 10 秒的超时形同虚设（实测慢站点整整卡了 15 秒）。
        # 正确做法：手动 shutdown(wait=False)，把卡住的线程当"孤儿"丢下不管。
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_fetch, url)
        try:
            html = future.result(timeout=WATCHDOG_SECONDS)
        except FutureTimeout as exc:
            future.cancel()
            pool.shutdown(wait=False)
            raise WebScrapeError("抓取超过 %d 秒，已放弃（该站可能很慢或有反爬）" % WATCHDOG_SECONDS) from exc
        finally:
            # 正常结束时也走这里；wait=False 保证绝不阻塞主流程
            pool.shutdown(wait=False)

        body = _clean_text(html)
        if not body:
            raise WebScrapeError(
                "抓到页面了，但没解析出正文（该站正文可能不是 <p> 标签，或内容是 JS 渲染的）"
            )

        cost = time.perf_counter() - started

        # ---- 3000 字硬截断 ----
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + "\n……（正文过长，已截断到 %d 字）" % MAX_CHARS

        # 这一行会出现在内核日志里，方便确认“真的抓到了什么”
        print(
            "      抓取完成：%s | 耗时 %.2f 秒 | 正文 %d 字"
            % (urlparse(url).netloc, cost, len(body)),
            flush=True,
        )
        return body


# -------------------------------------------------------------------------
# 自测：直接 python plugins/web_scraper_网页抓取.py <网址>
# 内核 import 本模块时 __name__ 不是 "__main__"，不会触发这段
# -------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    plugin = WebScraper()
    try:
        out = plugin.execute(target)
        print("=" * 60)
        print(out[:800])
        print("=" * 60)
        print("长度：%d 字" % len(out))
    except Exception as exc:
        print("[抓取失败] %s" % exc)

# -*- coding: utf-8 -*-
"""web_scraper 插件的边界测试：截断、超时、各种错误输入。"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# 测试用本地 HTTP server，只允许测试进程访问 loopback。
os.environ.setdefault("FW_ALLOW_PRIVATE_NETWORK", "1")

sys.path.insert(0, "plugins")
cwd = os.getcwd()
sys.path.insert(0, os.path.join(cwd, "plugins"))

# 插件文件名改成「英文_中文.py」了，按路径加载（别用 import 名字）
from core.loader_模块加载 import load as _load_plugin  # noqa: E402

_ws = _load_plugin("plugins/web_scraper_网页抓取.py", "test_web_scraper_mod")
WebScraper = _ws.WebScraper
WebScrapeError = _ws.WebScrapeError
MAX_CHARS = _ws.MAX_CHARS

LONG_PARAGRAPH = "这是一段很长的正文内容，用来测试三千字硬截断是否生效。" * 40


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/long":
            body = "<html><body>" + "".join("<p>%s</p>" % LONG_PARAGRAPH for _ in range(5)) + "</body></html>"
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/slow":
            # 故意慢慢吐：先发头，然后睡 15 秒，模拟 slowloris
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            for _ in range(15):
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(1)
        elif self.path == "/empty":
            data = "<html><body><div>div 堆的正文，没有 p 标签</div></body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
plugin = WebScraper()

passed = 0
failed = 0


def check(label, fn, expect_ok=True, expect_contains=None, max_seconds=None):
    global passed, failed
    t0 = time.perf_counter()
    try:
        out = fn()
        cost = time.perf_counter() - t0
        if not expect_ok:
            print("[FAIL] %s → 期望报错，实际成功" % label)
            failed += 1
            return
        if expect_contains and expect_contains not in out:
            print("[FAIL] %s → 输出里没有 %r" % (label, expect_contains))
            failed += 1
            return
        if max_seconds and cost > max_seconds:
            print("[FAIL] %s → 耗时 %.1fs 超过限制" % (label, cost))
            failed += 1
            return
        print("[PASS] %s（%.1fs，输出 %d 字）" % (label, cost, len(out)))
        passed += 1
    except WebScrapeError as exc:
        cost = time.perf_counter() - t0
        if expect_ok:
            print("[FAIL] %s → 意外报错：%s" % (label, exc))
            failed += 1
        else:
            if max_seconds and cost > max_seconds:
                print("[FAIL] %s → 报错花了 %.1fs，watchdog 没生效" % (label, cost))
                failed += 1
            else:
                print("[PASS] %s → 正确拦截：%s（%.1fs）" % (label, exc, cost))
                passed += 1


print("== 1. 正常抓取 ==")
check("example.com", lambda: plugin.execute("https://example.com"), expect_contains="domain")

print("\n== 2. 三千字硬截断 ==")
out = plugin.execute(base + "/long")
if len(out) <= MAX_CHARS + 40 and "已截断" in out:
    print("[PASS] 截断生效：%d 字（上限 %d）" % (len(out), MAX_CHARS))
    passed += 1
else:
    print("[FAIL] 截断没生效，输出 %d 字" % len(out))
    failed += 1

print("\n== 3. watchdog 10 秒超时 ==")
check("慢站点", lambda: plugin.execute(base + "/slow"), expect_ok=False, max_seconds=13)

print("\n== 4. 异常输入 ==")
check("空输入", lambda: plugin.execute(""), expect_ok=False)
check("没有网址", lambda: plugin.execute("帮我抓一下那个页面"), expect_ok=False)
check("404", lambda: plugin.execute(base + "/404"), expect_ok=False)
check("非法协议", lambda: plugin.execute("file:///C:/Windows/win.ini"), expect_ok=False)
check("无 p 标签", lambda: plugin.execute(base + "/empty"), expect_ok=False)

print("\n== 5. 从中文句子里抽网址 ==")
check("混合文本", lambda: plugin.execute("帮我抓一下 " + base + "/long 的内容"), expect_ok=True)

srv.shutdown()
print("\n结果：通过 %d，失败 %d" % (passed, failed))
sys.exit(0 if failed == 0 else 1)

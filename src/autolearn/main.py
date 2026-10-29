# AI_GENERATE_START --
# -*- coding: utf-8 -*-
"""系统自动学习工具 - CLI 直连模式入口。

用法：
  python main.py "探索系统有哪些业务菜单"   # 登录后交给 Agent 自主探索
  python main.py --probe <url>              # 感知测试：打开 URL 打印可交互元素后退出
  python main.py --fresh                    # 忽略已保存的登录态，重新登录

推荐用 MCP 模式（mcp_server.py）由 AI 助手当大脑，无需 LLM Key。
"""

import argparse
import asyncio
import sys

from playwright.async_api import async_playwright

from autolearn.agent import run_agent
from autolearn.config import DATA_DIR, HEADLESS, LLM_API_KEY, TARGET_URL
from autolearn.perceive import format_state, perceive
from autolearn.recorder import SessionRecorder

STATE_FILE = DATA_DIR / "state.json"


async def amain(args):
    target = args.probe or TARGET_URL
    if not target:
        print("错误：未配置 TARGET_URL，请在 .env 中设置，或用 --probe <url> 指定")
        sys.exit(1)
    if not args.probe and not LLM_API_KEY:
        print("错误：未配置 LLM_API_KEY。CLI 直连模式需要 Key；或改用 MCP 模式（AI 助手当大脑，无需 Key）")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS and not args.probe)
        context = await browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() and not args.fresh else None,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()
        print(f"打开目标系统: {target}")
        await page.goto(target, wait_until="domcontentloaded", timeout=60000)

        if args.probe:
            print(format_state(await perceive(page)))
            await browser.close()
            return

        if STATE_FILE.exists() and not args.fresh:
            print("已加载保存的登录态；若页面仍停留在登录页，请改用 --fresh 重新登录。")
        print("\n请在打开的浏览器窗口中完成登录（含验证码/短信等人工环节），")
        input("登录成功并看到系统首页后，回到这里按回车继续...")
        await context.storage_state(path=str(STATE_FILE))
        print(f"登录态已保存: {STATE_FILE}")

        goal = (args.goal or input("\n请输入探索目标: ")).strip()
        if not goal:
            print("错误：未提供探索目标")
            sys.exit(1)

        recorder = SessionRecorder(goal)
        print(f"会话目录: {recorder.session_dir}")
        try:
            ok, summary = await run_agent(page, context, goal, recorder)
            recorder.record("session_end", status="done" if ok else "stopped", summary=summary)
            print(f"\n探索结束: {summary}")
        except KeyboardInterrupt:
            recorder.record("session_end", status="interrupted", summary="用户中断")
        finally:
            print(f"情景记忆已写入: {recorder.file}")
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description="系统自动学习工具 - CLI 直连模式")
    parser.add_argument("goal", nargs="?", help="探索目标，如：探索系统有哪些业务菜单")
    parser.add_argument("--probe", metavar="URL", help="感知测试：打开 URL 打印页面状态后退出")
    parser.add_argument("--fresh", action="store_true", help="忽略已保存的登录态，重新登录")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
# AI_GENERATE_END --


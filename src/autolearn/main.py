# AI_GENERATE_START ----
# -*- coding: utf-8 -*-
"""系统自动学习工具 - CLI 直连模式入口。

用法：
  python main.py "探索系统有哪些业务菜单"          # 打开默认/上次系统，登录后交给 Agent 自主探索
  python main.py "探索XX" --system zfs            # 指定已注册系统（见 ~/.autolearn/data/systems/）
  python main.py "探索XX" --url https://a.com     # 任意网址（自动注册系统档案）
  python main.py --probe <url>                    # 感知测试：打开 URL 打印可交互元素后退出
  python main.py --fresh                          # 忽略已保存的登录态，重新登录

推荐用 MCP 模式（mcp_server.py）由 AI 助手当大脑，无需 LLM Key。
"""

import argparse
import asyncio
import sys

from playwright.async_api import async_playwright

from autolearn.agent import run_agent
from autolearn._bootstrap import launch_chromium
from autolearn.config import DATA_DIR, HEADLESS, LLM_API_KEY
from autolearn.perceive import format_state, perceive
from autolearn.recorder import SessionRecorder
from autolearn.systems import resolve_system, set_last_system, system_state_file


async def amain(args):
    if args.system:
        slug, target, err = resolve_system(system=args.system)
        if slug is None:
            print(f"错误：{err}")
            sys.exit(1)
    elif args.url:
        slug, target, err = resolve_system(url=args.url)
        if slug is None:
            print(f"错误：{err}")
            sys.exit(1)
    else:
        slug, target, err = resolve_system()
        if slug is None:
            print("错误：未指定系统。请用 --system <已注册系统名> / --url <网址>，或配置 TARGET_URL")
            sys.exit(1)
    state_file = system_state_file(slug)
    if not args.probe and not LLM_API_KEY:
        print("错误：未配置 LLM_API_KEY。CLI 直连模式需要 Key；或改用 MCP 模式（AI 助手当大脑，无需 Key）")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    set_last_system(slug)

    async with async_playwright() as p:
        browser = await launch_chromium(p, HEADLESS and not args.probe)
        context = await browser.new_context(
            storage_state=str(state_file) if state_file.exists() and not args.fresh else None,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()
        print(f"打开系统 {slug}: {target}")
        await page.goto(target, wait_until="domcontentloaded", timeout=60000)

        if args.probe:
            print(format_state(await perceive(page)))
            await browser.close()
            return

        if state_file.exists() and not args.fresh:
            print("已加载保存的登录态；若页面仍停留在登录页，请改用 --fresh 重新登录。")
        print("\n请在打开的浏览器窗口中完成登录（含验证码/短信等人工环节），")
        input("登录成功并看到系统首页后，回到这里按回车继续...")
        await context.storage_state(path=str(state_file))
        print(f"登录态已保存（系统 {slug}）: {state_file}")

        goal = (args.goal or input("\n请输入探索目标: ")).strip()
        if not goal:
            print("错误：未提供探索目标")
            sys.exit(1)

        recorder = SessionRecorder(goal, slug)
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
    parser = argparse.ArgumentParser(description="系统自动学习工具 - CLI 直连模式（支持多系统）")
    parser.add_argument("goal", nargs="?", help="探索目标，如：探索系统有哪些业务菜单")
    parser.add_argument("--system", metavar="NAME", help="已注册系统名（省略则用上次/TARGET_URL 系统）")
    parser.add_argument("--url", metavar="URL", help="直接指定任意网址（自动注册系统档案）")
    parser.add_argument("--probe", metavar="URL", help="感知测试：打开 URL 打印页面状态后退出")
    parser.add_argument("--fresh", action="store_true", help="忽略已保存的登录态，重新登录")
    asyncio.run(amain(parser.parse_args()))


if __name__ == "__main__":
    main()
# AI_GENERATE_END ----

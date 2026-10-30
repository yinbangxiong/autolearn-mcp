<!-- AI_GENERATE_START -- -->
# autolearn-mcp

自动学习浏览器/桌面应用 MCP Server：让任意支持 MCP 的 AI 助手（Trae / Claude / Cursor / Codex...）
成为你的"眼睛和手"——自主探索**任意 Web 系统/网页**与 **Windows 桌面应用**（不限单一系统）、
回放学会的操作、并把经验沉淀成三层记忆（情景轨迹 / 语义知识 / 操作技能），越用越聪明。

**大脑由 AI 助手担任**（无需单独的 LLM API Key），本包只提供感知、执行与记忆。

## 桌面应用探索（Windows）

`open_system(url="app://应用名")` 即可绑定已打开的桌面应用窗口（按窗口标题/类名子串匹配，
如 `app://记事本`、`app://计算器`），感知/操作仅限该窗口：

- 感知：UIA 控件树 → 交互元素编号（Button/Edit/MenuItem/ListItem 等），使用方式与 Web 一致；
- 动作：`click` / `click_text` / `type`（ValuePattern 优先，中文安全） / `select` / `scroll` / `key`（SendKeys 语法）/ `drag`；
- 每步窗口截图归档；应用未打开时工具会列出当前可见窗口供选择；
- 记忆按系统归档（slug 为 `app_应用名`），暂不支持技能回放；
- 注意：以管理员权限运行的应用（如任务管理器）需 autolearn 同权限才能感知。

## 多系统学习

`open_system(url=任意网址)` 即可探索任何网页/系统；登录态、凭据、记忆、技能、会话轨迹
全部**按系统自动归档**（slug 由域名自动生成，也可用 `list_systems` 查看已注册系统）：

```
~/.autolearn/
├── .env                        # 全局配置（TARGET_URL 为默认系统兜底）
├── credentials.json            # 各系统登录凭据 {"系统slug": {"username","password"}}
└── data/
    ├── systems/
    │   ├── zfs/                # 每个系统一个档案目录
    │   │   ├── profile.json    # 名称/URL/描述/类型
    │   │   ├── state.json      # 该系统登录态（互不覆盖）
    │   │   └── memory/         # 该系统语义记忆 + 技能 + 索引
    │   └── _global/            # 跨系统通用记忆（任何系统可读写/回放）
    └── sessions/<slug>/<ts>/   # 情景记忆按系统归档
```

要点：
- 登录态按系统隔离：探索系统 B 不会覆盖系统 A 的登录态；
- 技能按系统归属：`run_skill` 会拒绝跨系统回放，`_global` 技能任何系统可用；
- `recall` 无参数返回跨系统总览，传 `system` 查指定系统；
- 凭据支持多系统：`credentials.json` 按系统条目优先，回退 `.env` 全局 `AUTO_USERNAME/AUTO_PASSWORD`；
- 自动登录三级策略：通用登录策略链（自动找账号/密码框）→ 回放该系统 `login` 技能 → 转人工。

## 安装

```bash
# 推荐：uvx 一键运行（无需管理 Python 环境）
uvx autolearn-mcp

# 或 pip 安装
pip install autolearn-mcp
autolearn-install        # 首次自检：优先复用系统 Chrome/Edge，缺失时才下载内核
```

要求：Python ≥ 3.10。首次启动优先复用系统 Chrome/Edge（免下载）；两者都不可用时才自动下载 Chromium（进度走 stderr）。

> 国内网络建议配镜像：`pip install autolearn-mcp -i https://pypi.tuna.tsinghua.edu.cn/simple`

## 配置

配置文件位于 `~/.autolearn/.env`（也可用环境变量 / `AUTOLEARN_HOME` 自定义目录）：

```ini
TARGET_URL=http://your-system/          # 默认系统地址（open_system 无参时兜底）
AUTO_USERNAME=                          # 全局登录凭据（默认系统用；多系统见 credentials.json）
AUTO_PASSWORD=
HEADLESS=false                          # 是否无头模式（人工登录需要 false）
```

## 接入 AI 工具

**Trae / Claude Desktop / Cursor（通用 stdio）：**

```json
{
  "mcpServers": {
    "autolearn": { "command": "uvx", "args": ["autolearn-mcp"] }
  }
}
```

**Claude Code：**

```bash
claude mcp add autolearn -- uvx autolearn-mcp
```

**Codex CLI（config.toml）：**

```toml
[mcp_servers.autolearn]
command = "uvx"
args = ["autolearn-mcp"]
```

## 工具清单

| 工具 | 作用 |
|---|---|
| `list_systems()` | 列出已注册系统档案（记忆概况/登录态） |
| `open_system(system, url, goal)` | 打开目标系统/网页/桌面应用（`app://应用名`），开始探索会话（自动注册档案） |
| `auto_login()` | 自动登录当前系统（通用策略 → login 技能 → 人工兜底） |
| `save_login_state()` | 保存登录态到当前系统档案，下次免登录 |
| `perceive_page()` | 读取页面可交互元素（iframe 穿透 + 自动截图） |
| `act(action_json, expect_name)` | 执行动作（点击/输入/拖拽/链式），返回最新页面状态 |
| `run_skill(skill_id, params)` | 回放已沉淀的操作技能（归属校验 + 自愈 + 校验） |
| `recall(query, system)` | 检索记忆（跨系统总览 / 指定系统） |
| `export_memory_digest(system)` | 导出未消化轨迹，供大脑蒸馏 |
| `save_semantic_memory(system)` / `save_skill(system)` | 写入语义知识 / 操作技能（按系统归档） |
| `finish(summary)` | 结束会话 |

## 典型用法

1. `open_system(url=...)` 打开任意系统/网页（首次人工登录，之后 `auto_login` 免密）
2. 让 AI 助手自主探索：它感知页面 → 决策 → 执行 → 记录
3. 会话结束调用沉淀工具，轨迹蒸馏为该系统的记忆
4. 下次同类任务 `run_skill` 直接回放，越用越快；换系统探索互不干扰

数据全部落在本地 `~/.autolearn/`（记忆、截图、登录态、凭据），不上传任何服务器。
<!-- AI_GENERATE_END -- -->

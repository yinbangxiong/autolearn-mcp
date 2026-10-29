# autolearn-mcp

自动学习浏览器 MCP Server：让任意支持 MCP 的 AI 助手（Trae / Claude / Cursor / Codex...）
成为你的"眼睛和手"——自主探索 Web 系统、回放学会的操作、并把经验沉淀成三层记忆
（情景轨迹 / 语义知识 / 操作技能），越用越聪明。

**大脑由 AI 助手担任**（无需单独的 LLM API Key），本包只提供感知、执行与记忆。

## 安装

```bash
# 推荐：uvx 一键运行（无需管理 Python 环境）
uvx autolearn-mcp

# 或 pip 安装
pip install autolearn-mcp
autolearn-install        # 首次使用：下载 Chromium 内核（约 200MB，仅需一次）
```

要求：Python ≥ 3.10。首次启动会自动检测并下载 Chromium（进度走 stderr）。

> 国内网络建议配镜像：`pip install autolearn-mcp -i https://pypi.tuna.tsinghua.edu.cn/simple`

## 配置

配置文件位于 `~/.autolearn/.env`（也可用环境变量 / `AUTOLEARN_HOME` 自定义目录）：

```ini
TARGET_URL=http://your-system/          # 目标系统地址（建议测试环境）
AUTO_USERNAME=                          # 可选：自动登录账号
AUTO_PASSWORD=                          # 可选：自动登录密码
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
| `open_system(url, goal)` | 打开目标系统，开始探索会话（自动建记录） |
| `auto_login()` | 用 .env 凭据自动登录（成功自动保存登录态） |
| `save_login_state()` | 保存登录态，下次免登录 |
| `perceive_page()` | 读取页面可交互元素（iframe 穿透 + 自动截图） |
| `act(action_json, expect_name)` | 执行动作（点击/输入/链式），返回最新页面状态 |
| `run_skill(skill_id, params)` | 回放已沉淀的操作技能（自愈 + 校验） |
| `recall(query)` | 检索记忆，任务前注入历史经验 |
| `export_memory_digest()` | 导出未消化轨迹，供大脑蒸馏 |
| `save_semantic_memory()` / `save_skill()` | 写入语义知识 / 操作技能 |
| `finish(summary)` | 结束会话 |

## 典型用法

1. `open_system` 打开系统（首次人工登录，之后 `auto_login` 免密）
2. 让 AI 助手自主探索：它感知页面 → 决策 → 执行 → 记录
3. 会话结束调用沉淀工具，轨迹蒸馏为记忆
4. 下次同类任务 `run_skill` 直接回放，越用越快

数据全部落在本地 `~/.autolearn/`（记忆、截图、登录态），不上传任何服务器。

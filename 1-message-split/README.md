# 1. Message Split

让 bot 一次回复发**多条**短消息，而不是一整段。

## 它做什么

打 patch 后：claude 在 reply 工具里写文本时用空行（`\n\n`）分段 → server 自动拆成多条独立 Telegram 消息逐条发出，每条之间可加"对方正在输入..."指示器。

**Before**:
```
[bot] 哦你来啦我刚刚还在想你呢今天怎么样
```
**After**:
```
[bot] 哦
[bot] 你来啦                         ← 中间有 600ms "正在输入..." 间隔
[bot] 我刚还在想你呢
[bot] 今天怎么样
```

## 装

### 第一步：找到官方 telegram plugin 的 server.ts

| 系统 | 路径 |
|---|---|
| macOS / Linux | `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts` |
| Windows | `%USERPROFILE%\.claude\plugins\marketplaces\claude-plugins-official\external_plugins\telegram\server.ts` |

### 第二步：跑 patch 脚本

**macOS / Linux:**
```bash
python3 1-message-split/apply.py \
  ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
```

**Windows (PowerShell):**
```powershell
python 1-message-split\apply.py `
  "$env:USERPROFILE\.claude\plugins\marketplaces\claude-plugins-official\external_plugins\telegram\server.ts"
```

跑完会在同目录留一份 `server.ts.bak` 作为备份。脚本是幂等的，可以反复跑。

### 第三步：在 bot 的 access.json 里开关

bot 的 access.json 通常在 `~/.claude/channels/<bot_name>/access.json` 或类似位置。加两个字段：

```json
{
  "splitOnParagraph": true,
  "paragraphDelay": 600
}
```

| 字段 | 含义 | 推荐值 |
|---|---|---|
| `splitOnParagraph` | 总开关。`false` 或不设 = 行为跟未打 patch 一样 | `true` |
| `paragraphDelay` | 段间延时（毫秒），延时期间显示"正在输入..." | `400-800` |

### 第四步：让 claude 知道要分段写

在 bot 的 `CLAUDE.md` 加一段：

```markdown
回复规则：
- 一次回复用空行分段（`\n\n`），每段会自动发成独立 Telegram 消息
- 一次最多 3-5 段，每段 < 30 字
- 调一次 reply 工具发完所有段，不要多次调用
```

### 第五步：重启 bot 看效果

按你跑 bot 的方式重启（kill tmux session 让它重启 / 重新跑 claude CLI 等）。

## 卸

**macOS / Linux:**
```bash
bash 1-message-split/revert.sh \
  ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
```

**Windows (PowerShell):**
```powershell
copy "$env:USERPROFILE\.claude\plugins\marketplaces\claude-plugins-official\external_plugins\telegram\server.ts.bak" `
     "$env:USERPROFILE\.claude\plugins\marketplaces\claude-plugins-official\external_plugins\telegram\server.ts"
```

或者把 `splitOnParagraph` 设回 `false`，行为就退回原状（不需要恢复 server.ts）。

## 排错

| 现象 | 原因 |
|---|---|
| 跑 apply.py 输出 "no changes (already patched)" | 已经打过了，不是 bug |
| 消息还是一整条不拆 | access.json 里 `splitOnParagraph` 没设 / 没设 `true` / bot 没重启 |
| 报 "error: ... not found" | server.ts 路径写错了，确认上面表里的位置 |
| 官方 plugin 升级后再跑 patch 不生效 | 上游字符串可能改了，本 patch 用字符串匹配。提 issue 或自己改 apply.py 里的 selector |

## 文件

| 文件 | 用途 |
|---|---|
| `apply.py` | 打 patch 脚本（幂等） |
| `revert.sh` | 从 .bak 恢复（仅 macOS/Linux；Windows 用 copy 命令） |

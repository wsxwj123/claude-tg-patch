# Message Split Plugin

让 Telegram bot 一次回复发**多条消息**。

## 是什么

官方 [`claude-plugins/telegram`](https://github.com/anthropics/claude-code/tree/main/plugins/telegram) 默认行为：claude 一次 `reply()` → 一条 Telegram 消息（超长才按字符数硬切）。

打这个 patch 后：claude 写 reply 时用空行（`\n\n`）分段，server 自动拆成多条独立的 Telegram 消息逐条发出，每条之间有可选的"对方正在输入…"指示器。

效果对比：

```
打 patch 前：
  [一条长消息整段发出来]

打 patch 后：
  [bot] 哦
  [bot] 你来啦
  [bot] 我刚还在想你呢
```

更接近真人聊天节奏。

## 装

1. 装好官方 `claude-plugins/telegram` 并能正常跑通
2. 找到它的 `server.ts`：通常在
   ```
   ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
   ```
3. 跑：
   ```bash
   python apply.py ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
   ```
   会生成同目录下的 `server.ts.bak` 作为备份。
4. 在你 bot 的 `access.json` 里加两个字段：
   ```json
   {
     "splitOnParagraph": true,
     "paragraphDelay": 600
   }
   ```
   - `splitOnParagraph`：开关。`false` 或不设 = 行为跟未打 patch 一样
   - `paragraphDelay`：段间等待毫秒，0 = 不等。建议 400-800

## 让 claude 知道这个能力

加一段到 bot 的 `CLAUDE.md`：

```markdown
回复规则：
- 一次回复用空行分段（`\n\n`）。每段会被自动发成独立的 Telegram 消息。
- 一次最多 3-5 段，每段 < 30 字。
- 调一次 `reply` 工具发完所有段，不要多次 reply。
```

## 卸

```bash
bash revert.sh ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
```

或者直接 `cp server.ts.bak server.ts`。

## 已知

- `apply.py` 是幂等的，可以反复跑
- 官方 plugin 升级后选择器可能失效。这时 `apply.py` 会静默跳过有问题的步骤但不报错。失败标志：发消息还是一整条。重新装官方 plugin（恢复成最新版）→ 再跑 apply.py

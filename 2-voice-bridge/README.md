# Voice Bridge

让 Telegram bot 收发**语音消息**：用户发语音 → ASR 转文字给 claude；claude 回复 → TTS 转语音发回去。

## 是什么

两件事：

1. **入站 ASR**：bot 收到 Telegram voice message → 自动调 SenseVoice 转写中文（含情绪标签）→ 当作普通文字给 claude。
2. **出站 TTS**：claude 调 `reply` 工具时多传一个 `as_voice: true` → server 调 Fish Audio S2 把文本变成语音 → Telegram sendVoice 发出去。

支持：
- 段落拆分（配合 [`message-split`](../1-message-split)，每段一条独立语音消息）
- 行内情绪标签（`[娇喘地]`、`[叹气]`）
- 双语模式（中文文字气泡 + 日文语音气泡）

## 架构

```
[Telegram] ─voice msg─▶ [official telegram plugin]
                              ↓ MCP call
                        [server.py] (stdio thin proxy)
                              ↓ HTTP
                        [server_http.py] (FastAPI, 端口 7788)
                              ↓
                  ┌──────────┴──────────┐
                  ↓                     ↓
            [SenseVoice 本地]      [Fish Audio API]
              ASR 转写              TTS 合成
```

`server_http.py` 常驻，一份 SenseVoice 模型给所有 bot 共享。

## 装

### 1. 装 Python 依赖

```bash
cd 2-voice-bridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

第一次跑会从 ModelScope 下载 SenseVoice 模型到 `./models/`，约 1GB，需要十几分钟。墙内速度还行。

### 2. 配 API key

```bash
cp .env.example .env
# 编辑 .env，填 FISH_AUDIO_API_KEY 和 TELEGRAM_BOT_TOKEN
```

`FISH_AUDIO_API_KEY` 在 https://fish.audio 注册拿。S2 TTS 按字符计费，不便宜但音色可挑。

### 3. 启动 HTTP 服务

```bash
./start.sh start
./start.sh status     # 看是否健康
./start.sh stop
```

健康检查 `curl http://127.0.0.1:7788/health` 应返回 `{"ok": true}`。

### 4. 把 MCP server 注册到 bot

把 `mcp-snippet.json` 里的 `voice-bridge` 段并入 bot 的 `.mcp.json`（每个 bot 一份）。注意把 `${VOICE_BRIDGE_DIR}` 换成你 voice-bridge 的真实绝对路径——JSON 不识别 `~`。

例：
```json
{
  "mcpServers": {
    "voice-bridge": {
      "command": "/Users/you/voice-bridge/.venv/bin/python",
      "args": ["/Users/you/voice-bridge/server.py"],
      "env": {}
    }
  }
}
```

### 5. 给 telegram plugin 打补丁（加 `as_voice` 参数）

```bash
.venv/bin/python apply_patch.py ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
```

这会给 reply 工具新增 `as_voice` / `voice_emotion` / `voice_instruct` 三个参数，并让 reply handler 在 `as_voice=true` 时走 TTS 路径。

### 6. 在 bot 的 access.json 里加 voiceId

```json
{
  "voiceId": "你在 fish.audio 选的音色 ID"
}
```

不设这个字段，`as_voice=true` 会忽略并回退文字。

### 7. 同步 CLAUDE.md 提示词（可选但推荐）

让 claude 知道 ASR/TTS 怎么用：

```bash
python sync_snippet.py /path/to/your/bot/CLAUDE.md
```

会在你的 CLAUDE.md 里追加两段（用 HTML 注释包起来，可以反复跑覆盖更新）：
- `VOICE-REPLY-*`：何时用语音回复
- `GROUP-AUTOCHAT-*`：群聊场景说明（可选）

或者你直接 cat 这两个 snippet 文件 `CLAUDE-*-snippet.md` 看内容，自己 cp 进去。

## 文件用途

| 文件 | 是什么 |
|---|---|
| `server_http.py` | FastAPI 主服务，接 ASR 和 TTS 请求，调 SenseVoice 和 Fish Audio |
| `server.py` | MCP stdio 薄代理，bot 通过它访问 HTTP server |
| `apply_patch.py` | 给官方 telegram plugin 的 server.ts 加 `as_voice` 参数 |
| `sync_snippet.py` | 把 CLAUDE.md 片段同步到指定文件 |
| `start.sh` | 启动 / 停止 / 重启 HTTP 服务 |
| `CLAUDE-*-snippet.md` | 提示词模板，告诉 claude 怎么用语音 |
| `mcp-snippet.json` | MCP 注册示例 |

## 已知坑

- **首次启动慢**：要下 SenseVoice 模型
- **proxy 必须配对**：如果你跑代理，Fish Audio API 需要走代理（`HTTPS_PROXY`），但 SenseVoice 是本地推理不需要
- **macOS GPU**：funasr 默认 CPU 推理。Apple Silicon 想用 MPS 要自己改 `server_http.py` 加 `device='mps'`
- **段落拆分**：要先装 [`1-message-split`](../1-message-split)，否则一条长语音不会拆成多条

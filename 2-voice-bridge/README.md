# 2. Voice Bridge

让 bot 收发**语音消息**。用户发语音 → bot 听懂回复；claude 回复 → 用语音发回去。

## 它做什么

两个独立功能：

### 入站 ASR（语音 → 文字）
用户在 Telegram 给 bot 发一条 voice message → bot 后台调本地 [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) 模型转写成中文（含情绪标签 `HAPPY/SAD/ANGRY` 等） → claude 收到的是普通文字消息加上情绪元数据。

### 出站 TTS（文字 → 语音）
claude 调 reply 工具时多传一个 `as_voice: true` → server 把文本送到 [Fish Audio](https://fish.audio) S2 TTS 合成成 mp3 → 通过 Telegram sendVoice 发回去。

支持：
- 段落拆分（配合 [`1-message-split`](../1-message-split)，每段一条独立语音）
- 行内情绪标签：`今天好累呀。[叹气] 但看到你就好了。`
- 双语模式：中文文字气泡 + 日文语音气泡（适合配日文音色）

## 取 API key

### Fish Audio（必需）

1. 注册：https://fish.audio
2. 充值：右上角 → Billing → 添加余额。S2 模型按字符计费，**1 万字符约 $0.5**，先充 $5 够用很久
3. 拿 API key：右上角 → API → 生成新 key（只显示一次，存好）
4. 选音色（重要）：
   - 进 https://fish.audio 主页浏览 voice library
   - 试听挑一个，点进详情页
   - URL 里 `https://fish.audio/m/<这一段就是 voice_id>`
   - 或者 API → Models → 搜你喜欢的音色，复制其 model id

把 voice_id 等下要填到 bot 的 `access.json` 里的 `voiceId` 字段。

### Telegram bot token（必需）

如果你已经在用官方 telegram plugin，这个 token 你已经有了，跟原来用同一个。

没有的话：在 Telegram 里 @BotFather → /newbot → 跟着流程走，最后给你一个形如 `1234567890:AAH....` 的 token。

## 装（macOS / Linux）

### 第一步：装 Python 依赖

```bash
cd 2-voice-bridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

会装 fastapi、uvicorn、httpx、torch、funasr。**torch 很大（~1GB），首次安装慢**。

### 第二步：填配置

```bash
cp .env.example .env
nano .env       # 或用你喜欢的编辑器
```

要填：
```
FISH_AUDIO_API_KEY=fa-xxxxxxx              # 上面拿到的 Fish Audio key
TELEGRAM_BOT_TOKEN=1234567890:AAH...       # 你 bot 的 token
HTTPS_PROXY=http://127.0.0.1:7897          # 可选，需代理才填
```

### 第三步：启动 HTTP 服务

```bash
chmod +x start.sh
./start.sh start
./start.sh status      # 健康检查
```

**第一次启动会下载 SenseVoice 模型 ~1GB 到 `./models/`**，需要几到十几分钟。墙内速度看 ModelScope 的网络。

健康检查应返回：
```bash
curl http://127.0.0.1:7788/health
# {"ok": true, "asr_loaded": true}
```

### 第四步：把 MCP server 注册到 bot

打开 `mcp-snippet.json`，把 `voice-bridge` 这一段并入 bot 的 `.mcp.json`（每个 bot 一份）。

⚠️ **JSON 不支持 `~` 和环境变量**，必须写**绝对路径**：

```json
{
  "mcpServers": {
    "voice-bridge": {
      "command": "/Users/yourname/claude-tg-patch/2-voice-bridge/.venv/bin/python",
      "args": ["/Users/yourname/claude-tg-patch/2-voice-bridge/server.py"],
      "env": {}
    }
  }
}
```

### 第五步：给 telegram plugin 打补丁（加 `as_voice` 参数）

```bash
.venv/bin/python apply_patch.py \
  ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts
```

这会给 reply 工具新增 `as_voice` / `voice_emotion` / `voice_instruct` 参数。

### 第六步：bot 的 access.json 里加 voiceId

```json
{
  "voiceId": "上面 Fish Audio 选的音色 id"
}
```

不设这个字段时，`as_voice=true` 会被忽略并回退文字。

### 第七步：同步 CLAUDE.md 提示词

```bash
.venv/bin/python sync_snippet.py ~/.claude/<bot 名>/CLAUDE.md
```

会把两段提示词追加进 CLAUDE.md（用 HTML 注释包起来，可以反复跑覆盖更新）。也可以手动 cat snippet 文件 cv 进去。

### 第八步：重启 bot 试

发个语音消息看 bot 能不能回复 + 让 claude 试着用 `as_voice=true` 发语音回来。

## 装（Windows，PowerShell）

```powershell
cd 2-voice-bridge
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

copy .env.example .env
notepad .env     # 填 FISH_AUDIO_API_KEY 和 TELEGRAM_BOT_TOKEN

# Windows 没有 start.sh，直接跑（前台）
.venv\Scripts\python.exe server_http.py

# 或后台跑（新开 PowerShell 终端）
Start-Process -NoNewWindow .venv\Scripts\python.exe -ArgumentList server_http.py -RedirectStandardOutput logs\http_server.out
```

健康检查：`Invoke-WebRequest http://127.0.0.1:7788/health`

补丁脚本和 sync_snippet.py 一样跑：
```powershell
.venv\Scripts\python.exe apply_patch.py "$env:USERPROFILE\.claude\plugins\marketplaces\claude-plugins-official\external_plugins\telegram\server.ts"
.venv\Scripts\python.exe sync_snippet.py "$env:USERPROFILE\.claude\<bot 名>\CLAUDE.md"
```

`mcp-snippet.json` 里的路径改成 Windows 绝对路径：
```json
"command": "C:\\Users\\yourname\\claude-tg-patch\\2-voice-bridge\\.venv\\Scripts\\python.exe",
"args": ["C:\\Users\\yourname\\claude-tg-patch\\2-voice-bridge\\server.py"]
```

## 用法（claude 角度）

bot 的 CLAUDE.md 已经被 sync_snippet.py 注入了规则，claude 会自己判断什么时候用语音。手动控制例子：

```json
// 让 reply 发语音（普通）
{ "chat_id": "...", "text": "今天好累呀。", "as_voice": true }

// 带情绪
{ "chat_id": "...", "text": "[叹气] 又加班。", "as_voice": true, "voice_emotion": "SAD" }

// 双语：中文文字气泡 + 日文语音气泡
{
  "chat_id": "...",
  "text": "今天好累呀。",
  "voice_text": "今日はとても疲れたよ。",
  "as_voice": true
}
```

## 排错

| 现象 | 原因 / 修法 |
|---|---|
| `start.sh: Permission denied` | `chmod +x start.sh` |
| `.venv/bin/python: No such file` | 没建 venv，回到第一步 |
| `curl /health` 不通 | 看 `logs/http_server.out`，多半是 funasr 模型下载中或失败 |
| 模型下载卡住 | 设 `HTTPS_PROXY` 走代理；或从 ModelScope 手动下后放 `models/` |
| `apply_patch.py` 跑完语音功能没动 | 上游 plugin 升级了。看 `apply_patch.py` 报告，可能要改字符串选择器 |
| `as_voice=true` 没反应 | bot 的 access.json 没 voiceId / .mcp.json 没注册 voice-bridge / claude 没重启 |
| 语音被消息和文字双发 | 正常行为：`text` 是文字气泡，`voice_text` 是语音内容（可空） |

## 文件

| 文件 | 用途 |
|---|---|
| `server_http.py` | FastAPI 主服务，听 7788。处理 ASR / TTS / sendVoice |
| `server.py` | MCP stdio 薄代理。bot 通过它访问 HTTP server |
| `apply_patch.py` | 给 telegram plugin 加 `as_voice` 等参数 |
| `sync_snippet.py` | 把 CLAUDE.md 片段注入指定文件 |
| `start.sh` | macOS/Linux 启停脚本（Windows 直接跑 server_http.py） |
| `mcp-snippet.json` | MCP 注册示例（要手填绝对路径） |
| `CLAUDE-*.md` | 提示词模板，告诉 claude 怎么用语音 |
| `requirements.txt` | Python 依赖清单 |

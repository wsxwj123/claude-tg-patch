# Claude TG Patch

三个独立模块，给 [Claude Code](https://docs.claude.com/en/docs/claude-code) 官方的 telegram plugin 加功能。每个模块独立，按需装。

---

## 它们能干嘛

### 1. [Message Split](./1-message-split/) — 把一段长回复拆成多条消息

**改前**：bot 一次回复一整段长消息
```
[bot] 哦你来啦我刚刚还在想你呢今天感觉怎么样啊有没有发生什么有趣的事
```

**改后**：用空行分段，自动拆成多条独立消息发出，模拟真人打字节奏
```
[bot] 哦
[bot] 你来啦
[bot] 我刚还在想你呢
[bot] 今天怎么样
```

### 2. [Voice Bridge](./2-voice-bridge/) — 收发语音消息

- **入站**：用户发 Telegram voice → 自动用 SenseVoice 转写成中文（带情绪标签）→ 当文字给 claude
- **出站**：claude 调 reply 时多传一个 `as_voice=true` → 用 Fish Audio S2 合成成语音 → 发回 Telegram

支持段落分多条语音、行内情绪标签（`[娇喘地]` `[叹气]` 等）、双语模式（中文文字气泡 + 日文语音气泡）。

### 3. [NovelAI Skill](./3-skill-novelai/) — 让 claude 生图发图

- 用户说"自拍一张" → claude 调 NovelAI 生图 → 发到 Telegram
- 自动按场景挑尺寸（自拍/全身用竖图 832×1216；远景用横图 1216×832）
- "再来一张换个动作" → 同一个 seed，房间/床/灯光保持一致

---

## 跑起来要什么

| | 必需 | 用来干嘛 |
|---|---|---|
| Claude Code CLI | ✅ | 已 `claude /login` 过 |
| Telegram bot 已能跑 | ✅ | [官方 telegram plugin](https://docs.claude.com/en/docs/claude-code/plugins) 装好且能给 bot 发文字消息收到回复 |
| Python 3.10+ | ✅ | 三个模块都用 |
| Bun | ✅ | telegram plugin 自身用 |
| Fish Audio API key | 仅模块 2 | TTS 合成（fish.audio 注册付费） |
| NovelAI 订阅 | 仅模块 3 | 出图 |

支持 **macOS / Linux / Windows**。Windows 用户用 PowerShell 或 Git Bash 都行。

---

## 装

```bash
git clone https://github.com/wsxwj123/claude-tg-patch.git
cd claude-tg-patch
```

然后按需装 1 / 2 / 3：每个目录有独立 README，照着 30 分钟内能跑起来。

**推荐顺序**：先装 `1-message-split`（5 分钟，立竿见影）→ 再装 `3-skill-novelai`（10 分钟）→ 最后装 `2-voice-bridge`（30 分钟，要下 1GB 模型）。

---

## 整套跑通后的效果

```
你：在干嘛
bot：[三条消息分发]
     在床上躺着
     你呢
     刚还在想你

你：[发语音]"无聊死了"
bot：[识别为 NEUTRAL 情绪]
     无聊就找点事做嘛
     [并发了一段语音]

你：来张自拍
bot：[NovelAI 生图，自动选 portrait 832×1216]
     [发图]

你：再来一张换个动作
bot：[同房间、同床、同灯光，只换姿势]
```

---

## License

MIT — see [LICENSE](./LICENSE)。

## 来源

抽自一个跑了几个月的本地三 bot 系统，洗掉私有人设、token、路径后开源。

**没**自动化部署（launchd/systemd）、**没** multi-tenant、**没** CI——单机自用工程。能跑通要看你折腾劲。

## 不保证

- 官方 telegram plugin 升级后字符串选择器可能失效，patch 脚本会跳过；自己看输出
- Fish Audio / NovelAI 是付费服务，自己买
- claude CLI 的 OAuth token 长期续命有坑（worker 进程 env 冻结），不在本仓库范围内

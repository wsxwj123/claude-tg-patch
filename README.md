# Claude Code Telegram Extras

三个独立模块，给官方 [`claude-plugins/telegram`](https://github.com/anthropics/claude-code) 加点东西。

| 模块 | 做什么 | 依赖 |
|---|---|---|
| [`1-message-split`](./1-message-split) | 一次回复拆成多条消息发出去（更像真人） | 无 |
| [`2-voice-bridge`](./2-voice-bridge) | 收发语音消息（ASR + TTS） | Fish Audio API + 本地 SenseVoice 模型 |
| [`3-skill-novelai`](./3-skill-novelai) | 让 claude 生图发图，按场景选尺寸，续图保持一致性 | NovelAI 订阅 |

每个目录是独立的，按需装。

## 前置

- 已装好 [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI 并 `claude /login`
- 已装好官方 telegram plugin（在 `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/`）并能跑通基础 bot
- macOS / Linux（Windows 没测过）
- Python 3.10+
- Bun（仅 telegram plugin 自身需要）

## 推荐安装顺序

1. 先把官方 telegram plugin 跑通（能给 bot 发文字消息收到回复）
2. 装 [`1-message-split`](./1-message-split) — 立即能改善聊天体验
3. 装 [`3-skill-novelai`](./3-skill-novelai) — 如果你想发图
4. 装 [`2-voice-bridge`](./2-voice-bridge) — 最重，要下 1GB 本地模型 + Fish Audio 订阅，按需

## 三模块组合效果

全装好之后，你跟 bot 的对话能像这样：

```
你：在干嘛
bot：[分了三条消息]
     在床上躺着
     你呢
     刚刚还在想你

你：[发语音]"无聊死了"
bot：[语音转写：无聊死了 (NEUTRAL)]
     ...回复...
     [并发了一段语音]

你：来张自拍
bot：[NovelAI 生图，自动选 portrait 832×1216]
     [发图]

你：再来一张换个角度
bot：[同一房间、同样的床，只换姿势]
```

## License

MIT — see [LICENSE](./LICENSE)。

## 来源

抽自一个跑了若干月的本地 3-bot 系统，去掉私有人设、token、路径后开源出来。
没自动化部署脚本（launchd/systemd）、没 multi-tenant、没 CI——单机自用工程。

## 不保证

- 官方 telegram plugin 升级后字符串选择器可能失效，patch 脚本会跳过；自己看输出
- NovelAI / Fish Audio 是付费服务，自己买
- claude CLI 的 OAuth token 长期续命有坑（worker 进程 env 冻结），不在本仓库范围内

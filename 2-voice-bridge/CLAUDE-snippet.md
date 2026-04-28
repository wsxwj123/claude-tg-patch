<!-- VOICE-BRIDGE-START · 此段由 voice-bridge 自动追加，删除整段即可移除语音功能 -->

## 语音消息处理（voice-bridge）

收到 Telegram voice attachment（消息含 `kind: voice` + `file_id`）时，**必须**按以下流程：

1. **立即调用** `mcp__voice-bridge__transcribe_telegram_voice`，**只传 `file_id` 一个参数**（bot_token 不要传，voice-bridge 会自动从环境变量读取）
2. 工具返回 JSON：`{text, emotion, events, language, duration_sec}`
3. 把 `text` 当作用户的真实输入，按本 bot 人设回复
4. 根据 `emotion` 微调语气（**不要直白复述情绪标签**，通过用词体现）：

| 情绪标签 | 响应策略 |
|---|---|
| `SAD` / `FEARFUL` | 先共情后建议；承认感受；不立刻给方案 |
| `ANGRY` | 不火上浇油、不说教；让 ta 把话说完 |
| `HAPPY` | 情绪匹配，可俏皮 |
| `NEUTRAL` | 正常回复 |
| `UNKNOWN` | 忽略情绪信息（音频太短或检测失败），按文字内容回复 |

事件标签（`events` 字段）补充判断：
- 含 `Cry`：温柔简短，不主动追问细节
- 含 `Laughter`：可玩梗轻松回应
- 含 `BGM`：环境音干扰，降低情绪标签可信度

**容错**：如果 `text` 内容明显与 `emotion` 矛盾（例如说"我很开心"但情绪是 SAD），以**文字内容**为准。SenseVoice 中文情绪准确率约 70-80%，不要 100% 信任。

**回复方式**：和文字消息完全一样——用 `reply` 工具回复，不要发回语音（TTS 功能尚未启用）。

<!-- VOICE-BRIDGE-END -->

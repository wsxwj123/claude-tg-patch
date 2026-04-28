# NovelAI Image Skill

让 claude 调 NovelAI 生图，按场景挑尺寸（自拍/全身/远景），同场景续图保持一致性。

## 是什么

一个 Claude Code 用户级 skill。用户在 Telegram 跟 bot 说"自拍一张"，bot 走这个 skill：
1. 写 prompt 中间稿（intermediate.json）
2. 跑 `generate_novelai_image.py`：拼前后缀 → 调 NovelAI → 存图 → 返回路径
3. 把图发到 Telegram

特性：
- **`--ratio`**：portrait / landscape / square / wide 四种预设，AI 按场景自动挑
- **`--reuse-seed`**：同场景续图复用上一次 seed，房间/床/灯光保持一致
- 持久化 `last_request.json`，可"再来一张同样的"
- NSFW 触发自动加 prefix

## 装

### 1. 拷到用户级 skill 目录

```bash
mkdir -p ~/.claude/skills
cp -r . ~/.claude/skills/novelai-skill
```

Claude CLI 启动时会自动扫这个目录。

### 2. 配 NovelAI token

```bash
cd ~/.claude/skills/novelai-skill
cp .env.example .env.local
# 编辑 .env.local，填 NOVELAI_BEARER_TOKEN
```

token 从 https://novelai.net 控制台拿（Account → Get Persistent API Token）。需要 NovelAI 订阅。

### 3. 调一下默认输出目录（可选）

`.env.local` 里可设 `NOVELAI_OUTPUT_DIR`。默认 `~/novelai-output/<agent>/<session>/`。

### 4. 调风格

`assets/default_config.json` 的 `positive_prefix` 是默认风格前缀。当前是 generic 质量词。要做自己的风格就在这里加：

- 艺术家：`artist:xxx::, artist:yyy::`
- 角色锚点：`1.1::your_character_id::`（把 character LoRA 嵌进 prompt）
- 风格修饰：`photorealistic`, `anime style`, `flat color` 等

权重语法走 NovelAI 标准（`数字::token::`）。

## 用

bot 那边的 CLAUDE.md 加一段：

```markdown
发图规则：
- 当用户要图，调 ~/.claude/skills/novelai-skill 走文生图
- 按场景挑 --ratio：自拍/全身用 portrait，远景用 landscape
- 续图（"再来一张"）必传 --reuse-seed + intermediate.json mode=revise
- 生图成功后只发图不啰嗦
```

实际命令模板（SKILL.md 里有详细规则）：

```bash
# 新场景
python3 ~/.claude/skills/novelai-skill/scripts/generate_novelai_image.py \
  --intermediate /tmp/agent1/intermediate.json \
  --config ~/.claude/skills/novelai-skill/assets/default_config.json \
  --ratio portrait \
  --agent-name agent1 \
  --session-name session1

# 同场景续图（保持房间/床一致）
python3 ~/.claude/skills/novelai-skill/scripts/generate_novelai_image.py \
  --intermediate /tmp/agent1/intermediate.json \
  --config ~/.claude/skills/novelai-skill/assets/default_config.json \
  --ratio portrait \
  --reuse-seed \
  --agent-name agent1 \
  --session-name session1
```

intermediate.json 例（新场景）：
```json
{
  "prompt": "1girl, lying on bed, white sheets, soft window light, casual pose"
}
```

intermediate.json 例（续图）：
```json
{
  "mode": "revise",
  "revision_instruction": "spread legs slightly, lift skirt"
}
```

## 文件清单

| 文件 | 作用 |
|---|---|
| `SKILL.md` | claude 看的：何时该调本 skill、prompt 写法、`--ratio` 决策表、续图规则 |
| `scripts/generate_novelai_image.py` | 主入口：调 NovelAI API、保存图、记录 last_request |
| `scripts/prompt_builder.py` | 拼前后缀、检测 NSFW、处理 mode=revise 的 prompt 沿用 |
| `assets/default_config.json` | 默认尺寸 / steps / cfg / sampler / 前后缀 |
| `assets/chat_mappings.json` | 中文续图触发词列表（"再来一张" 等） |

## 已知坑

- **artist anchor 是关键变量**：默认 prefix 不带任何艺术家，出图风格平淡。要好看必须自己加 1-3 个 NovelAI 支持的艺术家
- **`--reuse-seed` 不是万能的**：seed 一致只是噪声起点一致，prompt 大改还是会变。仅适合"同场景小改"
- **NovelAI 限流**：账号免费/付费都有日配额，超了脚本会报 429
- **proxy**：如果你网络环境需要代理才能访问 image.novelai.net，export `HTTPS_PROXY` 即可

## 卸

直接 `rm -rf ~/.claude/skills/novelai-skill`。

# 3. NovelAI Skill

让 claude 调 NovelAI 出图发图，按场景挑尺寸，续图保持一致性。

## 它做什么

一个 Claude Code 用户级 skill。装好后：

- 用户在 Telegram 跟 bot 说"自拍一张" → claude 自动调本 skill → 生图 → 发到聊天
- 自动按场景挑尺寸：自拍/全身/竖屏 → 832×1216；远景/录像 → 1216×832
- 续图（"再来一张换个动作"）自动用同一个 seed → 房间/床/灯光保持一致
- NSFW 内容自动加 prompt prefix，无需手动开关

## 取 NovelAI API key

1. 订阅：https://novelai.net
   - 必须是 **Tablet ($15/月)** 或更高档，免费档不能生图
   - Tablet 给 1000 个 Anlas/月，约够生 100-150 张图
2. 拿 token：登录后右上角 → Account → Get Persistent API Token
3. 复制那串很长的 token（一般以 `pst-` 开头），等下要填到 `.env.local`

## 装

### macOS / Linux

```bash
# 1. 拷到用户级 skill 目录（claude CLI 会自动扫这里）
mkdir -p ~/.claude/skills
cp -r 3-skill-novelai ~/.claude/skills/novelai-skill

# 2. 配 token
cd ~/.claude/skills/novelai-skill
cp .env.example .env.local
nano .env.local
```

### Windows (PowerShell)

```powershell
# 1. 拷到用户级 skill 目录
$skillDir = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force $skillDir | Out-Null
Copy-Item -Recurse 3-skill-novelai "$skillDir\novelai-skill"

# 2. 配 token
cd "$skillDir\novelai-skill"
copy .env.example .env.local
notepad .env.local
```

### .env.local 必填字段

```
NOVELAI_BEARER_TOKEN=pst-xxxxxxxxxxxxxxxx     # 上面拿到的那串

# 可选
# NOVELAI_OUTPUT_DIR=~/Downloads/novelai-output    # 默认 ~/novelai-output/
# HTTPS_PROXY=http://127.0.0.1:7897                # 需要代理才填
```

### 让 bot 知道用这个 skill

在 bot 的 `CLAUDE.md` 末尾加一段：

**macOS / Linux 路径写法：**
```markdown
## 发图规则
- 当用户要图（自拍、照片、来一张...），调 ~/.claude/skills/novelai-skill 出图
- 必传 --ratio：自拍/全身用 portrait；远景/录像用 landscape；特写用 square
- 续图（"再来一张"/"换个动作"）必传 --reuse-seed + intermediate.json 里设 mode=revise
- 生成成功后只发图和 1-2 句简短回复，不要描述图片内容代替发图
```

**Windows 用户**：路径换成 `%USERPROFILE%\.claude\skills\novelai-skill`，命令模板用 `python` 而非 `python3`。

## 调风格（可选但强烈建议）

`assets/default_config.json` 的 `positive_prefix` 现在是**裸的**质量词，出图风格寡淡。要好看必须加自己的：

打开 `~/.claude/skills/novelai-skill/assets/default_config.json`，修改：

```json
"positive_prefix": "5::best quality, masterpiece, very aesthetic, detailed, absurdres::, 1.5::artist:你喜欢的艺术家1::, 1.2::artist:艺术家2::, year 2025"
```

NovelAI v4.5 支持的艺术家见官方支持表（搜 "NovelAI Diffusion V4 artist tags"）。常用：
- `wlop`, `kantoku`, `mika_pikazo`, `redjuice` 等
- 数字是权重，0.5-2.0 之间

要复制某个特定角色的画风，搜"NovelAI v4 character anchor" 学习用法。

## 用法（claude 角度）

bot 收到"自拍一张"，claude 内部应该这样跑：

**新场景（默认）：**

```bash
# macOS / Linux
python3 ~/.claude/skills/novelai-skill/scripts/generate_novelai_image.py \
  --intermediate /tmp/agent1/intermediate.json \
  --config ~/.claude/skills/novelai-skill/assets/default_config.json \
  --ratio portrait \
  --agent-name agent1 \
  --session-name <chat_id>

# Windows
python "$env:USERPROFILE\.claude\skills\novelai-skill\scripts\generate_novelai_image.py" `
  --intermediate "$env:TEMP\agent1\intermediate.json" `
  --config "$env:USERPROFILE\.claude\skills\novelai-skill\assets\default_config.json" `
  --ratio portrait `
  --agent-name agent1 `
  --session-name <chat_id>
```

intermediate.json 长这样：
```json
{
  "prompt": "1girl, lying on bed, white sheets, soft window light, casual pose"
}
```

**同场景续图（保持一致性）：**

加 `--reuse-seed` flag，并把 intermediate.json 改成：
```json
{
  "mode": "revise",
  "revision_instruction": "spread legs slightly, lift skirt"
}
```
环境会自动从上一次沿用，只改你写的部分。

## --ratio 决策表（claude 自己选）

| 用户说的 | 选 | 尺寸 |
|---|---|---|
| 自拍 / 镜子前 / 半身 / 全身 / 立绘 / 站姿 | `portrait` | 832×1216 |
| 远处 / 远景 / 放在远处录像 / 房间环境 / 多人横排 | `landscape` | 1216×832 |
| 特写 / 脸部 / 头像 / 嘴特写 | `square` | 1024×1024 |
| 横躺全身 / 极宽景 | `wide` | 1536×640 |

详细规则在 `SKILL.md`。

## 排错

| 现象 | 原因 / 修法 |
|---|---|
| 报 401 Unauthorized | `.env.local` 里 token 错或过期，重新生成 |
| 报 429 Concurrent generation locked | 你的账号在别处也在生图，或并发太多。脚本会自动重试 3 次 |
| 报 quota exceeded | Anlas 用光了，等下个月或升级 Opus |
| 出图风格寡淡 | 默认 prefix 没艺术家，看上面"调风格"段 |
| 续图房间还是变 | 检查 claude 是不是真传了 `--reuse-seed`；上一张要先生成成功才能复用 seed |
| 中文 prompt 出图歪 | NovelAI 是英文模型，prompt 必须英文 booru tag。SKILL.md 里有写法规范 |

## 文件

| 文件 | 用途 |
|---|---|
| `SKILL.md` | claude 自己看的规范：何时调 skill、prompt 写法、ratio 决策、续图规则 |
| `scripts/generate_novelai_image.py` | 主入口：调 NovelAI、存图、记录 last_request |
| `scripts/prompt_builder.py` | 拼前后缀、检测 NSFW、处理 mode=revise |
| `assets/default_config.json` | 默认尺寸 / steps / cfg / sampler / 前后缀（**用户要改这个**） |
| `assets/chat_mappings.json` | 中文续图触发词列表 |
| `.env.example` | 配置模板，cp 成 `.env.local` |

## 卸

```bash
# macOS / Linux
rm -rf ~/.claude/skills/novelai-skill

# Windows PowerShell
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\novelai-skill"
```

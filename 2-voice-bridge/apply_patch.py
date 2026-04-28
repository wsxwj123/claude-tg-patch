#!/usr/bin/env python3
"""
voice-bridge 对 telegram plugin server.ts 的 patch
---------------------------------------------------
- Access 接口新增 voiceId 字段
- loadAccess 读 voiceId
- reply tool 新增 as_voice / voice_emotion / voice_instruct 参数
- reply handler 中根据 as_voice 走 TTS → sendVoice 分支

幂等：若标记已存在则跳过。

与 restart-bots.sh 中的 splitOnParagraph patch 并存。建议先跑原 patch，再跑本 patch。
"""
import re
import sys
from pathlib import Path

SERVER_FILE = Path(
    "~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/server.ts"
)

VOICE_BRIDGE_URL = "http://127.0.0.1:7788/send_voice"


def patch(content: str) -> str:
    # ---- 1. 类型定义：Access 接口加 voiceId / tmuxSession ----
    if "voiceId?:" not in content:
        content = content.replace(
            "paragraphDelay?: number",
            "paragraphDelay?: number\n  /** Fish Audio voice reference id. Enables as_voice replies if set. */\n  voiceId?: string\n  /** tmux session name for slash command bridge (e.g. 'tg-yourbot'). */\n  tmuxSession?: string",
        )

    # ---- 2. loadAccess：读取 voiceId / tmuxSession ----
    if "voiceId: parsed.voiceId" not in content:
        content = content.replace(
            "paragraphDelay: parsed.paragraphDelay,",
            "paragraphDelay: parsed.paragraphDelay,\n      voiceId: parsed.voiceId,\n      tmuxSession: parsed.tmuxSession,",
        )

    # ---- 3. reply tool schema：新增三个参数（只在 reply tool，不在 edit_message） ----
    if "as_voice:" not in content:
        # 用 files 参数（reply 独有）做锚点，精确定位 reply tool 的 format 字段
        old_reply_schema = (
            "          files: {\n"
            "            type: 'array',\n"
            "            items: { type: 'string' },\n"
            "            description: 'Absolute file paths to attach. Images send as photos (inline preview); other types as documents. Max 50MB each.',\n"
            "          },\n"
            "          format: {\n"
            "            type: 'string',\n"
            "            enum: ['text', 'markdownv2'],"
        )
        new_reply_schema = (
            "          files: {\n"
            "            type: 'array',\n"
            "            items: { type: 'string' },\n"
            "            description: 'Absolute file paths to attach. Images send as photos (inline preview); other types as documents. Max 50MB each.',\n"
            "          },\n"
            "          as_voice: {\n"
            "            type: 'boolean',\n"
            "            description: \"Send as voice message(s) via Fish Audio TTS instead of text. Requires voiceId in access.json. Preserves splitOnParagraph — each paragraph becomes one voice message. Default: false.\",\n"
            "          },\n"
            "          voice_emotion: {\n"
            "            type: 'string',\n"
            "            enum: ['HAPPY', 'SAD', 'ANGRY', 'NEUTRAL', 'FEARFUL', 'SURPRISED', 'DISGUSTED'],\n"
            "            description: \"Emotion tone for voice reply. Only used when as_voice=true.\",\n"
            "          },\n"
            "          voice_instruct: {\n"
            "            type: 'string',\n"
            "            description: \"Free-form instruction for voice delivery, e.g. '用撒娇温柔的语气说'. Overrides voice_emotion preset. Only used when as_voice=true.\",\n"
            "          },\n"
            "          voice_text: {\n"
            "            type: 'string',\n"
            "            description: \"Alternate text that becomes the VOICE content (only, not displayed). If set with as_voice=true: text bubble shows `text` (e.g. Chinese), voice bubble speaks `voice_text` (e.g. Japanese). Must have SAME paragraph count as text (\\\\n\\\\n-separated). If omitted with as_voice=true: text is both displayed and spoken. Ignored when as_voice=false.\",\n"
            "          },\n"
            "          format: {\n"
            "            type: 'string',\n"
            "            enum: ['text', 'markdownv2'],"
        )
        content = content.replace(old_reply_schema, new_reply_schema)

    # ---- 4. reply handler：as_voice 分支 ----
    # 标记：as_voice 处理代码
    if "// VOICE-BRIDGE-TTS" not in content:
        # 4a. 在 case 'reply' 开始处解析参数
        old_parse = (
            "        const format = (args.format as string | undefined) ?? 'text'\n"
            "        const parseMode = format === 'markdownv2' ? 'MarkdownV2' as const : undefined"
        )
        new_parse = (
            "        const format = (args.format as string | undefined) ?? 'text'\n"
            "        const parseMode = format === 'markdownv2' ? 'MarkdownV2' as const : undefined\n"
            "        // VOICE-BRIDGE-TTS: as_voice / voice_emotion / voice_instruct / voice_text\n"
            "        const asVoice = args.as_voice === true\n"
            "        const voiceEmotion = (args.voice_emotion as string | undefined) ?? 'NEUTRAL'\n"
            "        const voiceInstruct = (args.voice_instruct as string | undefined) ?? ''\n"
            "        const voiceTextRaw = (args.voice_text as string | undefined) ?? ''\n"
            "        // voice_text 按段落拆分，与 allChunks 一一对应。\n"
            "        // 保留空段：空段表示该对应 text 段只发文本气泡、不朗读（如角色内心独白）。\n"
            "        const voiceChunks: string[] = asVoice && voiceTextRaw\n"
            "          ? voiceTextRaw.split('\\n\\n').map(s => s.trim())\n"
            "          : []"
        )
        content = content.replace(old_parse, new_parse)

        # 4b. sendMessage 循环替换为条件分支
        #     as_voice=true 时：POST voice-bridge /send_voice（Python httpx 代理正常，绕开 Bun fetch multipart+proxy bug）
        old_loop = (
            "            const sent = await bot.api.sendMessage(chat_id, allChunks[i], {\n"
            "              ...(shouldReplyTo ? { reply_parameters: { message_id: reply_to } } : {}),\n"
            "              ...(parseMode ? { parse_mode: parseMode } : {}),\n"
            "            })\n"
            "            sentIds.push(sent.message_id)"
        )
        new_loop = (
            "            if (asVoice) {\n"
            "              // VOICE-BRIDGE-TTS: voice-bridge 一体化 TTS+sendVoice（绕开 Bun fetch multipart+proxy bug）\n"
            "              const voiceId = access.voiceId\n"
            "              if (!voiceId) throw new Error('as_voice=true but access.json missing voiceId')\n"
            "              // voice_text 提供时：先发文本（显示语言），后发语音（朗读语言）；否则纯语音\n"
            "              const hasDual = voiceChunks.length > 0\n"
            "              // 段数不对齐或对应段为空 → 跳过 TTS（用于内心独白段只显示文本）\n"
            "              const ttsText = hasDual ? (voiceChunks[i] ?? '') : allChunks[i]\n"
            "              const skipVoice = !ttsText || ttsText.trim() === ''\n"
            "              if (hasDual) {\n"
            "                const sentText = await bot.api.sendMessage(chat_id, allChunks[i], {\n"
            "                  ...(shouldReplyTo ? { reply_parameters: { message_id: reply_to } } : {}),\n"
            "                  ...(parseMode ? { parse_mode: parseMode } : {}),\n"
            "                })\n"
            "                sentIds.push(sentText.message_id)\n"
            "              }\n"
            "              if (!skipVoice) {\n"
            "                const vResp = await fetch('" + VOICE_BRIDGE_URL + "', {\n"
            "                  method: 'POST',\n"
            "                  headers: { 'Content-Type': 'application/json' },\n"
            "                  body: JSON.stringify({\n"
            "                    bot_token: bot.token,\n"
            "                    chat_id: String(chat_id),\n"
            "                    text: ttsText,\n"
            "                    voice_id: voiceId,\n"
            "                    emotion: voiceEmotion,\n"
            "                    instruct: voiceInstruct,\n"
            "                    // 双语模式下语音不再 reply-quote（文本已 quote）\n"
            "                    reply_to_message_id: (shouldReplyTo && !hasDual) ? reply_to : undefined,\n"
            "                  }),\n"
            "                })\n"
            "                if (!vResp.ok) {\n"
            "                  const errText = await vResp.text().catch(() => '')\n"
            "                  throw new Error(`voice-bridge send_voice ${vResp.status}: ${errText}`)\n"
            "                }\n"
            "                const { message_id } = await vResp.json() as { message_id: number }\n"
            "                sentIds.push(message_id)\n"
            "              }\n"
            "            } else {\n"
            "              const sent = await bot.api.sendMessage(chat_id, allChunks[i], {\n"
            "                ...(shouldReplyTo ? { reply_parameters: { message_id: reply_to } } : {}),\n"
            "                ...(parseMode ? { parse_mode: parseMode } : {}),\n"
            "              })\n"
            "              sentIds.push(sent.message_id)\n"
            "            }"
        )
        content = content.replace(old_loop, new_loop)

    # ---- 5. 文件发送走 voice-bridge /send_file（绕开 Bun fetch multipart+proxy bug）----
    if "// VOICE-BRIDGE-SENDFILE" not in content:
        old_files_loop = (
            "        for (const f of files) {\n"
            "          const ext = extname(f).toLowerCase()\n"
            "          const input = new InputFile(f)\n"
            "          const opts = reply_to != null && replyMode !== 'off'\n"
            "            ? { reply_parameters: { message_id: reply_to } }\n"
            "            : undefined\n"
            "          if (PHOTO_EXTS.has(ext)) {\n"
            "            const sent = await bot.api.sendPhoto(chat_id, input, opts)\n"
            "            sentIds.push(sent.message_id)\n"
            "          } else {\n"
            "            const sent = await bot.api.sendDocument(chat_id, input, opts)\n"
            "            sentIds.push(sent.message_id)\n"
            "          }\n"
            "        }"
        )
        new_files_loop = (
            "        // VOICE-BRIDGE-SENDFILE: Python httpx 绕开 Bun fetch multipart+proxy bug\n"
            "        for (const f of files) {\n"
            "          const ext = extname(f).toLowerCase()\n"
            "          const kind = PHOTO_EXTS.has(ext) ? 'photo' : 'document'\n"
            "          const replyToId = (reply_to != null && replyMode !== 'off') ? reply_to : undefined\n"
            "          const fResp = await fetch('http://127.0.0.1:7788/send_file', {\n"
            "            method: 'POST',\n"
            "            headers: { 'Content-Type': 'application/json' },\n"
            "            body: JSON.stringify({\n"
            "              bot_token: bot.token,\n"
            "              chat_id: String(chat_id),\n"
            "              file_path: f,\n"
            "              kind,\n"
            "              reply_to_message_id: replyToId,\n"
            "            }),\n"
            "          })\n"
            "          if (!fResp.ok) {\n"
            "            const errText = await fResp.text().catch(() => '')\n"
            "            throw new Error(`voice-bridge send_file ${fResp.status}: ${errText}`)\n"
            "          }\n"
            "          const { message_id } = await fResp.json() as { message_id: number }\n"
            "          sentIds.push(message_id)\n"
            "        }"
        )
        content = content.replace(old_files_loop, new_files_loop)

    # ---- 6. 群路由：多 bot 群聊指向性判定 ----
    # GroupPolicy 扩展 + decideGroupReply 函数 + gate 群分支改造 + meta 增强
    if "// GROUP-ROUTER" not in content:
        # 6a. GroupPolicy 类型扩展
        content = content.replace(
            "type GroupPolicy = {\n"
            "  requireMention: boolean\n"
            "  allowFrom: string[]\n"
            "}",
            "type GroupPolicy = {\n"
            "  requireMention: boolean\n"
            "  allowFrom: string[]\n"
            "  /** 本 bot 在群里的中文别名，任一出现即视为被点名。仅对人类发送者生效。 */\n"
            "  selfAliases?: string[]\n"
            "  /** 群里其他 bot 的 @username（含 @），用于识别『只点了别人』的场景。 */\n"
            "  otherBotUsernames?: string[]\n"
            "  /** 群里其他 bot 的中文别名，用于识别『只点了别人』的场景（仅对人类发送者生效）。 */\n"
            "  otherBotAliases?: string[]\n"
            "}",
        )

        # 6b. 在 isMentioned 之后插入 decideGroupReply
        anchor = (
            "  for (const pat of extraPatterns ?? []) {\n"
            "    try {"
        )
        if anchor in content and "function decideGroupReply" not in content:
            new_func = (
                "// GROUP-ROUTER: 多 bot 群聊指向性判定\n"
                "// - 人类发来：点我（@ 或别名 或 TG-reply 到我的消息）→ 回；点别人没点我 → 不回；无指向 → 回\n"
                "// - bot 发来：仅 text entities 里有 @我 username 才回（TG-reply 不算，防回环；别名不算，防误触）\n"
                "function hasExplicitEntityMention(ctx: Context): boolean {\n"
                "  const entities = ctx.message?.entities ?? ctx.message?.caption_entities ?? []\n"
                "  const text = ctx.message?.text ?? ctx.message?.caption ?? ''\n"
                "  for (const e of entities) {\n"
                "    if (e.type === 'mention') {\n"
                "      const mentioned = text.slice(e.offset, e.offset + e.length)\n"
                "      if (mentioned.toLowerCase() === `@${botUsername}`.toLowerCase()) return true\n"
                "    }\n"
                "    if (e.type === 'text_mention' && e.user?.is_bot && e.user.username === botUsername) {\n"
                "      return true\n"
                "    }\n"
                "  }\n"
                "  return false\n"
                "}\n"
                "\n"
                "function decideGroupReply(\n"
                "  ctx: Context,\n"
                "  policy: GroupPolicy,\n"
                "  extraPatterns?: string[],\n"
                "): 'reply' | 'drop' {\n"
                "  const text = ctx.message?.text ?? ctx.message?.caption ?? ''\n"
                "  const isBotSender = ctx.from?.is_bot === true\n"
                "\n"
                "  if (isBotSender) {\n"
                "    // 严格：只认 entities 里的显式 @，不认 TG-reply 链、不认别名、不认 extraPatterns\n"
                "    return hasExplicitEntityMention(ctx) ? 'reply' : 'drop'\n"
                "  }\n"
                "\n"
                "  const myExplicit = isMentioned(ctx, extraPatterns)\n"
                "  const myAliasHit = (policy.selfAliases ?? []).some(a => a.length > 0 && text.includes(a))\n"
                "  const otherMentioned =\n"
                "    (policy.otherBotUsernames ?? []).some(u => u.length > 0 && text.toLowerCase().includes(u.toLowerCase())) ||\n"
                "    (policy.otherBotAliases   ?? []).some(a => a.length > 0 && text.includes(a))\n"
                "\n"
                "  if (myExplicit || myAliasHit) return 'reply'\n"
                "  if (otherMentioned) return 'drop'\n"
                "  return 'reply'\n"
                "}\n"
                "\n"
                "function isMentioned_disabled_noop() { /* placeholder to keep diff small */ }\n"
            )
            # 把 decideGroupReply 插到 isMentioned 函数结束之后、下一个函数/导出之前
            # 定位点：isMentioned 里 for pat loop 的那个 catch 块之后
            # 用正则匹配 isMentioned 末尾（catch 块的注释措辞可能变），抓到最后的 `  return false\n}` 行
            # 定位：在 isMentioned 函数体内的 for catch 块之后的第一个 `return false\n}`
            isment_end_re = re.compile(
                r"(for \(const pat of extraPatterns \?\? \[\]\) \{[\s\S]*?\n\s*\}\s*\n\s*return false\n\})",
                re.MULTILINE,
            )
            m = isment_end_re.search(content)
            if m:
                insertion = m.group(1) + "\n\n" + new_func.rstrip("\n")
                insertion = insertion.replace(
                    "\nfunction isMentioned_disabled_noop() { /* placeholder to keep diff small */ }",
                    ""
                )
                content = content[:m.start()] + insertion + content[m.end():]

        # 6c. gate 群分支改造：requireMention 单条判定 → decideGroupReply
        old_group_branch = (
            "    if (requireMention && !isMentioned(ctx, access.mentionPatterns)) {\n"
            "      return { action: 'drop' }\n"
            "    }\n"
            "    return { action: 'deliver', access }"
        )
        new_group_branch = (
            "    // GROUP-ROUTER: v1 兼容——若 selfAliases/otherBotUsernames/otherBotAliases 任一非空，走新路由；\n"
            "    // 否则回落到旧 requireMention 行为。\n"
            "    const hasRouterCfg =\n"
            "      (policy.selfAliases?.length ?? 0) > 0 ||\n"
            "      (policy.otherBotUsernames?.length ?? 0) > 0 ||\n"
            "      (policy.otherBotAliases?.length ?? 0) > 0\n"
            "    if (hasRouterCfg) {\n"
            "      const decision = decideGroupReply(ctx, policy, access.mentionPatterns)\n"
            "      if (decision === 'drop') return { action: 'drop' }\n"
            "      return { action: 'deliver', access }\n"
            "    }\n"
            "    if (requireMention && !isMentioned(ctx, access.mentionPatterns)) {\n"
            "      return { action: 'drop' }\n"
            "    }\n"
            "    return { action: 'deliver', access }"
        )
        content = content.replace(old_group_branch, new_group_branch)

        # 6d. meta 增强：chat_type / is_bot_sender / sender_username
        old_meta = (
            "        user: from.username ?? String(from.id),\n"
            "        user_id: String(from.id),\n"
            "        ts: new Date((ctx.message?.date ?? 0) * 1000).toISOString(),"
        )
        new_meta = (
            "        user: from.username ?? String(from.id),\n"
            "        user_id: String(from.id),\n"
            "        chat_type: ctx.chat?.type ?? 'private',\n"
            "        ...(from.is_bot ? { is_bot_sender: true } : {}),\n"
            "        ...(from.username ? { sender_username: from.username } : {}),\n"
            "        ts: new Date((ctx.message?.date ?? 0) * 1000).toISOString(),"
        )
        content = content.replace(old_meta, new_meta)

    # ---- 7. 群聊共享 transcript：gate 通过后写 JSONL，带 rotation + attachment 信息 ----
    if "// GROUP-TRANSCRIPT" not in content:
        # 7a. 确保 appendFileSync 已被 import
        content = content.replace(
            "import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync, statSync, renameSync, realpathSync, chmodSync } from 'fs'",
            "import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync, statSync, renameSync, realpathSync, chmodSync, appendFileSync } from 'fs'",
        )
        # 7b. 在 imagePath 解析之后、mcp.notification 之前插入 transcript 写入
        #     放这个位置：已过 gate（不会记录被 drop 的陌生人）+ imagePath 已 resolve（能带路径）
        anchor = (
            "  const imagePath = downloadImage ? await downloadImage() : undefined\n"
            "\n"
            "  // image_path goes in meta only — an in-content \"[image attached — read: PATH]\"\n"
            "  // annotation is forgeable by any allowlisted sender typing that string.\n"
            "  mcp.notification({"
        )
        injection = (
            "  const imagePath = downloadImage ? await downloadImage() : undefined\n"
            "\n"
            "  // GROUP-TRANSCRIPT: 群聊消息写入共享 JSONL，供所有 bot 回复前读取\n"
            "  // 已过 gate → 不记录被 allowFrom 丢弃的陌生人消息\n"
            "  const _chatType = ctx.chat?.type\n"
            "  if (_chatType === 'group' || _chatType === 'supergroup') {\n"
            "    try {\n"
            "      const tdir = join(homedir(), '.claude', 'channels', 'group_transcripts')\n"
            "      mkdirSync(tdir, { recursive: true })\n"
            "      const tpath = join(tdir, `${ctx.chat!.id}.jsonl`)\n"
            "      const line = JSON.stringify({\n"
            "        ts: new Date((ctx.message?.date ?? Date.now() / 1000) * 1000).toISOString(),\n"
            "        chat_id: String(ctx.chat!.id),\n"
            "        message_id: ctx.message?.message_id,\n"
            "        from_id: String(ctx.from?.id ?? ''),\n"
            "        from_username: ctx.from?.username ?? null,\n"
            "        is_bot: ctx.from?.is_bot === true,\n"
            "        text: (text ?? '').slice(0, 1000),\n"
            "        observed_by: botUsername,\n"
            "        ...(imagePath ? { image_path: imagePath } : {}),\n"
            "        ...(attachment ? { attachment_kind: attachment.kind, attachment_file_id: attachment.file_id } : {}),\n"
            "      }) + '\\n'\n"
            "      appendFileSync(tpath, line)\n"
            "      // Rotation：文件 > 5MB 时保留最后 2000 行\n"
            "      try {\n"
            "        const st = statSync(tpath)\n"
            "        if (st.size > 5 * 1024 * 1024) {\n"
            "          const all = readFileSync(tpath, 'utf8').split('\\n')\n"
            "          const kept = all.slice(Math.max(0, all.length - 2000)).join('\\n')\n"
            "          const tmp = tpath + '.tmp'\n"
            "          writeFileSync(tmp, kept)\n"
            "          renameSync(tmp, tpath)\n"
            "        }\n"
            "      } catch { /* rotation 非关键 */ }\n"
            "    } catch { /* transcript 是辅助功能，失败不阻断主流程 */ }\n"
            "  }\n"
            "\n"
            "  // image_path goes in meta only — an in-content \"[image attached — read: PATH]\"\n"
            "  // annotation is forgeable by any allowlisted sender typing that string.\n"
            "  mcp.notification({"
        )
        content = content.replace(anchor, injection)

    # ---- 8. 新增 MCP tool: add_group_alias（bot 调 tool 更新自己的 access.json） ----
    if "// ADD-GROUP-ALIAS-TOOL" not in content:
        # 8a. 在 tools 列表末尾 (edit_message 之后) 追加 tool schema
        content = content.replace(
            "      name: 'edit_message',\n"
            "      description: 'Edit a message the bot previously sent. Useful for interim progress updates. Edits don\\'t trigger push notifications — send a new reply when a long task completes so the user\\'s device pings.',",
            "      name: 'edit_message',\n"
            "      description: 'Edit a message the bot previously sent. Useful for interim progress updates. Edits don\\'t trigger push notifications — send a new reply when a long task completes so the user\\'s device pings.',",
        )
        # 在 tools 数组闭合 `],` 之前插入 add_group_alias schema
        old_tools_close = (
            "        required: ['chat_id', 'message_id', 'text'],\n"
            "      },\n"
            "    },\n"
            "  ],\n"
            "}))"
        )
        new_tools_close = (
            "        required: ['chat_id', 'message_id', 'text'],\n"
            "      },\n"
            "    },\n"
            "    {\n"
            "      // ADD-GROUP-ALIAS-TOOL\n"
            "      name: 'add_group_alias',\n"
            "      description: 'Persist a new alias for a group. Updates THIS bot\\'s own access.json atomically. Use kind=\"self\" when the user renames/nicknames YOU (appends to selfAliases). Use kind=\"other\" when the user gives a new name to ANOTHER bot in the same group (appends to otherBotAliases so you learn to stay quiet when that name is called). Dedup is automatic. Effective immediately (no restart).',\n"
            "      inputSchema: {\n"
            "        type: 'object',\n"
            "        properties: {\n"
            "          group_id: { type: 'string', description: 'Group chat_id (negative number as string)' },\n"
            "          alias: { type: 'string', description: 'The nickname/alias to add. 1-20 chars.' },\n"
            "          kind: { type: 'string', enum: ['self', 'other'], description: 'self = rename me; other = learn another bot\\'s new name' },\n"
            "        },\n"
            "        required: ['group_id', 'alias', 'kind'],\n"
            "      },\n"
            "    },\n"
            "  ],\n"
            "}))"
        )
        content = content.replace(old_tools_close, new_tools_close)

        # 8b. 在 switch default: 之前插入 case 'add_group_alias'
        old_default = (
            "      default:\n"
            "        return {\n"
            "          content: [{ type: 'text', text: `unknown tool: ${req.params.name}` }],"
        )
        new_default = (
            "      case 'add_group_alias': {\n"
            "        // ADD-GROUP-ALIAS-TOOL\n"
            "        const groupId = String(args.group_id)\n"
            "        const aliasRaw = String(args.alias ?? '').trim()\n"
            "        const kind = String(args.kind)\n"
            "        if (!aliasRaw || aliasRaw.length > 20) throw new Error('alias must be 1-20 chars')\n"
            "        if (kind !== 'self' && kind !== 'other') throw new Error('kind must be self|other')\n"
            "        if (!/^-?\\d+$/.test(groupId)) throw new Error('group_id must be numeric')\n"
            "        // 读当前 access.json（走原始文件，不经 loadAccess 缓存），加锁式原子替换\n"
            "        const raw = readFileSync(ACCESS_FILE, 'utf8')\n"
            "        const parsed = JSON.parse(raw)\n"
            "        parsed.groups = parsed.groups ?? {}\n"
            "        parsed.groups[groupId] = parsed.groups[groupId] ?? { requireMention: false, allowFrom: [] }\n"
            "        const g = parsed.groups[groupId]\n"
            "        const field = kind === 'self' ? 'selfAliases' : 'otherBotAliases'\n"
            "        const arr: string[] = Array.isArray(g[field]) ? g[field] : []\n"
            "        if (!arr.includes(aliasRaw)) arr.push(aliasRaw)\n"
            "        g[field] = arr\n"
            "        parsed.groups[groupId] = g\n"
            "        // 原子写\n"
            "        const tmp = ACCESS_FILE + '.tmp'\n"
            "        writeFileSync(tmp, JSON.stringify(parsed, null, 2) + '\\n', { mode: 0o600 })\n"
            "        renameSync(tmp, ACCESS_FILE)\n"
            "        return { content: [{ type: 'text', text: `ok: ${field} += ${aliasRaw} (${arr.length} total)` }] }\n"
            "      }\n"
            "      default:\n"
            "        return {\n"
            "          content: [{ type: 'text', text: `unknown tool: ${req.params.name}` }],"
        )
        content = content.replace(old_default, new_default)

    # ---- 9. ASR：voice 消息先转写再入 handleInbound ----
    if "// ASR-TRANSCRIBE" not in content:
        old_voice = (
            "bot.on('message:voice', async ctx => {\n"
            "  const voice = ctx.message.voice\n"
            "  const text = ctx.message.caption ?? '(voice message)'\n"
            "  await handleInbound(ctx, text, undefined, {\n"
            "    kind: 'voice',"
        )
        new_voice = (
            "bot.on('message:voice', async ctx => {\n"
            "  // ASR-TRANSCRIBE: 先向 voice-bridge 要 SenseVoice 转写，失败回落占位符\n"
            "  const voice = ctx.message.voice\n"
            "  let text = ctx.message.caption ?? '(voice message)'\n"
            "  try {\n"
            "    const r = await fetch('http://127.0.0.1:7788/transcribe_telegram', {\n"
            "      method: 'POST',\n"
            "      headers: { 'Content-Type': 'application/json' },\n"
            "      body: JSON.stringify({ file_id: voice.file_id, bot_token: bot.token }),\n"
            "    })\n"
            "    if (r.ok) {\n"
            "      const j = await r.json() as { text?: string }\n"
            "      if (j.text && j.text.trim()) text = j.text.trim()\n"
            "    }\n"
            "  } catch { /* ASR 失败保留占位符 */ }\n"
            "  await handleInbound(ctx, text, undefined, {\n"
            "    kind: 'voice',"
        )
        content = content.replace(old_voice, new_voice)

    # ---- 10. Slash 命令桥：Telegram 收到白名单 / 开头消息 → tmux send-keys 到 claude TUI ----
    if "// SLASH-BRIDGE" not in content:
        # 在 handleInbound 里、gate 通过后、permission reply 检测之前插入
        # 锚点：permission reply 前的注释行（稳定）
        anchor = (
            "  // Permission-reply intercept: if this looks like \"yes xxxxx\" for a\n"
            "  // pending permission request, emit the structured event instead of\n"
            "  // relaying as chat. The sender is already gate()-approved at this point\n"
            "  // (non-allowlisted senders were dropped above), so we trust the reply."
        )
        injection = (
            "  // SLASH-BRIDGE: 白名单 slash 命令 → 通过 tmux send-keys 注入本 bot 的 claude TUI\n"
            "  const SLASH_WHITELIST = ['/compact', '/usage', '/context', '/cost', '/model', '/clear', '/status']\n"
            "  // 先剥掉开头的 @<username> 前缀（群里必然带 @bot）\n"
            "  const _trimmed = text.trim().replace(/^@\\w+\\s+/, '').trim()\n"
            "  const _matched = SLASH_WHITELIST.find(s => _trimmed === s || _trimmed.startsWith(s + ' '))\n"
            "  if (_matched && access.tmuxSession) {\n"
            "    const _chatType2 = ctx.chat?.type\n"
            "    const _isGroup = _chatType2 === 'group' || _chatType2 === 'supergroup'\n"
            "    // 群里必须显式 @ 我，DM 无条件通过\n"
            "    if (!_isGroup || hasExplicitEntityMention(ctx)) {\n"
            "      try {\n"
            "        // tmux has-session 检测\n"
            "        const check = Bun.spawn(['tmux', 'has-session', '-t', access.tmuxSession])\n"
            "        await check.exited\n"
            "        if (check.exitCode !== 0) {\n"
            "          await bot.api.sendMessage(chat_id, `[tmux session ${access.tmuxSession} 不存在]`,\n"
            "            msgId != null ? { reply_parameters: { message_id: msgId } } : {})\n"
            "          return\n"
            "        }\n"
            "        // 用 -l 发字面文本（不解析为 key name），再单独发 Enter 键。\n"
            "        // 不能加 Escape——Escape 是 ANSI \\x1b，后续 '/c' 会被 TUI 吃掉当转义序列。\n"
            "        const sendText = Bun.spawn(['tmux', 'send-keys', '-t', access.tmuxSession, '-l', _trimmed])\n"
            "        await sendText.exited\n"
            "        const sendEnter = Bun.spawn(['tmux', 'send-keys', '-t', access.tmuxSession, 'Enter'])\n"
            "        await sendEnter.exited\n"
            "        await bot.api.sendMessage(chat_id, `已下发: ${_trimmed}`,\n"
            "          msgId != null ? { reply_parameters: { message_id: msgId } } : {})\n"
            "      } catch (e) {\n"
            "        await bot.api.sendMessage(chat_id, `[slash bridge 失败: ${String(e).slice(0, 200)}]`,\n"
            "          msgId != null ? { reply_parameters: { message_id: msgId } } : {})\n"
            "      }\n"
            "      return\n"
            "    }\n"
            "  }\n"
            "\n"
            "  // Permission-reply intercept: if this looks like \"yes xxxxx\" for a\n"
            "  // pending permission request, emit the structured event instead of\n"
            "  // relaying as chat. The sender is already gate()-approved at this point\n"
            "  // (non-allowlisted senders were dropped above), so we trust the reply."
        )
        content = content.replace(anchor, injection)

    return content


def main():
    if not SERVER_FILE.exists():
        print(f"✗ server.ts 未找到: {SERVER_FILE}")
        sys.exit(1)

    original = SERVER_FILE.read_text()
    patched = patch(original)

    if patched == original:
        print("已 patch（无变化）")
        return

    SERVER_FILE.write_text(patched)
    markers = ["voiceId?:", "voiceId: parsed.voiceId", "as_voice:", "VOICE-BRIDGE-TTS", "VOICE-BRIDGE-SENDFILE", "GROUP-ROUTER", "GROUP-TRANSCRIPT", "ADD-GROUP-ALIAS-TOOL", "ASR-TRANSCRIBE", "SLASH-BRIDGE"]
    added = sum(1 for marker in markers if marker in patched)
    print(f"✓ 已应用 voice-bridge patch ({added}/{len(markers)} 标记存在)")


if __name__ == "__main__":
    main()

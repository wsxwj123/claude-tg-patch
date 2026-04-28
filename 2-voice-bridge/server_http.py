"""
voice-bridge HTTP Server
========================
常驻 FastAPI 服务，所有 bot 共享：
  - SenseVoice STT（模型只加载一次，~2GB 内存共享）
  - Fish Audio TTS（云端 API，零额外内存）

端点：
  POST /transcribe_file          { path }                                  → STT
  POST /transcribe_telegram      { file_id, bot_token? }                   → STT
  POST /synthesize_voice         { text, voice_id, emotion?, format? }     → OGG bytes
  GET  /health                                                              → { ok, model_loaded }

运行：./start.sh  或  uvicorn server_http:app --host 127.0.0.1 --port 7788
"""
import os
import re
import sys
import json
import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Optional
from contextlib import asynccontextmanager

ROOT = Path(__file__).parent
MODEL_CACHE = ROOT / "models"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
MODEL_CACHE.mkdir(exist_ok=True)

os.environ["MODELSCOPE_CACHE"] = str(MODEL_CACHE)
os.environ["HF_HOME"] = str(MODEL_CACHE / "hf")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        # 5MB 一轮，保留 3 份（http_server.log + .1 + .2 + .3）→ 上限 ~20MB
        RotatingFileHandler(
            LOG_DIR / "http_server.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("voice-bridge-http")


def mask(s: str) -> str:
    if not s or len(s) < 12:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


# ---------- SenseVoice ----------
EMOTION_TAGS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED"}
EVENT_TAGS = {"BGM", "Speech", "Applause", "Laughter", "Cry"}
LANG_TAGS = {"zh", "en", "ja", "ko", "yue", "auto", "nospeech"}
TAG_RE = re.compile(r"<\|([^|]+)\|>")


def parse_sensevoice_output(raw: str, duration: float) -> dict[str, Any]:
    tags = TAG_RE.findall(raw)
    text = TAG_RE.sub("", raw).strip()
    emotion = "UNKNOWN"
    events: list[str] = []
    language = "unknown"
    for t in tags:
        if t in EMOTION_TAGS:
            emotion = t
        elif t in EVENT_TAGS:
            events.append(t)
        elif t in LANG_TAGS:
            language = t
    if duration < 1.5:
        emotion = "UNKNOWN"
    return {"text": text, "emotion": emotion, "events": events, "language": language}


_model = None
_model_lock = asyncio.Lock()


async def get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        log.info("加载 SenseVoice-Small 模型...")
        t0 = time.time()
        loop = asyncio.get_event_loop()
        from funasr import AutoModel

        def _load():
            return AutoModel(
                model="iic/SenseVoiceSmall",
                trust_remote_code=False,
                disable_update=True,
                device="cpu",
            )

        _model = await loop.run_in_executor(None, _load)
        log.info(f"✓ 模型加载完成 {time.time() - t0:.1f}s")
        return _model


async def transcribe_file(audio_path: str) -> dict[str, Any]:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(audio_path)

    import soundfile as sf
    try:
        info = sf.info(audio_path)
        duration = info.frames / info.samplerate
    except Exception:
        duration = 0.0

    model = await get_model()
    t0 = time.time()
    loop = asyncio.get_event_loop()

    def _infer():
        return model.generate(
            input=audio_path, cache={}, language="auto",
            use_itn=True, batch_size_s=60,
        )

    result = await loop.run_in_executor(None, _infer)
    latency = int((time.time() - t0) * 1000)
    raw = result[0]["text"] if result else ""
    parsed = parse_sensevoice_output(raw, duration)
    parsed["duration_sec"] = round(duration, 2)
    parsed["latency_ms"] = latency
    log.info(
        f"STT: {duration:.1f}s → {len(parsed['text'])}字, "
        f"情绪={parsed['emotion']}, 事件={parsed['events']}, {latency}ms"
    )
    return parsed


async def transcribe_telegram(file_id: str, bot_token: str = "") -> dict[str, Any]:
    import httpx
    if not bot_token or ":" not in bot_token or bot_token.startswith("$"):
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token or ":" not in bot_token:
        raise RuntimeError("bot_token 不可用")

    log.info(f"下载 Telegram 语音 file_id={file_id[:20]}... token={mask(bot_token)}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getFile 失败: {data}")
        file_path = data["result"]["file_path"]
        r2 = await client.get(
            f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        )
        r2.raise_for_status()
        suffix = Path(file_path).suffix or ".ogg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=LOG_DIR) as tmp:
            tmp.write(r2.content)
            tmp_path = tmp.name

    try:
        return await transcribe_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------- Fish Audio TTS ----------
FISH_API_BASE = "https://api.fish.audio/v1/tts"
FISH_MODEL_DEFAULT = "s2-pro"  # s2-pro 音质顶级（s1/s-mini/s2-pro 实测耗时差 <0.5s）

# Fish Audio 免费档 5 并发，付费 $100 档 15 并发。留一档冗余防 429。
FISH_CONCURRENCY = int(os.environ.get("FISH_AUDIO_CONCURRENCY", "4"))
_fish_sem = asyncio.Semaphore(FISH_CONCURRENCY)


def fish_api_key() -> str:
    key = os.environ.get("FISH_AUDIO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FISH_AUDIO_API_KEY 未设置")
    return key


# 情绪 → Fish Audio S2 行内方括号标签（官方推荐的 word-level voice direction）
# 参考 https://docs.fish.audio/developer-guide/getting-started/quickstart
# S2 能识别中文自然语言方括号指令，无需 SSML。AI 也可以直接在 text 里写 [声音颤抖]/[叹气] 等。
EMOTION_TAG = {
    "HAPPY":     "[开心地]",
    "SAD":       "[悲伤地]",
    "ANGRY":     "[愤怒地]",
    "FEARFUL":   "[害怕地，声音颤抖]",
    "SURPRISED": "[惊讶地]",
    "DISGUSTED": "[厌恶地]",
    "NEUTRAL":   "",  # 中性不加标签，避免干扰
}


async def synthesize_voice(
    text: str,
    voice_id: str,
    emotion: str = "NEUTRAL",
    instruct: str = "",
    model: str = FISH_MODEL_DEFAULT,
) -> bytes:
    """调用 Fish Audio 合成音频，返回 OGG/Opus bytes（Telegram sendVoice 可直用）"""
    import httpx
    import ormsgpack

    key = fish_api_key()

    # Fish S2 行内指令：优先 instruct（≤12 字转成 [xxx]），超长降级到 emotion 预设短标签
    # 原因：Fish S2 对长标签识别不稳定，超过某阈值会把 [xxx] 当字面量念出来（实测 38 字必念）。
    # AI 也可以直接在 text 里写 [标签]，此处前缀与之共存。
    MAX_INSTRUCT_TAG_LEN = 12
    prefix_parts: list[str] = []
    if instruct and len(instruct) <= MAX_INSTRUCT_TAG_LEN:
        prefix_parts.append(f"[{instruct}]")
    else:
        if instruct:
            log.warning(
                f"instruct 超过 {MAX_INSTRUCT_TAG_LEN} 字 ({len(instruct)} 字)，"
                f"降级到 emotion={emotion}: {instruct[:30]}..."
            )
        tag = EMOTION_TAG.get(emotion, "")
        if tag:
            prefix_parts.append(tag)
    final_text = ("".join(prefix_parts) + text) if prefix_parts else text

    payload = {
        "text": final_text,
        "reference_id": voice_id,
        "format": "mp3",           # 先拿 mp3 再 ffmpeg 转 opus
        "mp3_bitrate": 128,
        "chunk_length": 100,       # 更小分片 → 首字节更快返回
        "normalize": True,
        "latency": "balanced",     # balanced 比 normal 快 ~40%，音质差异不大
    }

    log.info(
        f"TTS: voice_id={voice_id[:8]}..., 情绪={emotion}, "
        f"文本={len(text)}字, instruct={bool(instruct)}, "
        f"in-flight={FISH_CONCURRENCY - _fish_sem._value}/{FISH_CONCURRENCY}"
    )
    t0 = time.time()
    async with _fish_sem:  # 并发限流：Fish Audio 免费档 5 并发上限
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                FISH_API_BASE,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/msgpack",
                    "model": model,
                },
                content=ormsgpack.packb(payload),
            )
            r.raise_for_status()
            mp3_bytes = r.content
    log.info(f"  Fish 返回 mp3 {len(mp3_bytes)} bytes, {int((time.time()-t0)*1000)}ms")

    # mp3 → ogg/opus (Telegram voice 格式)
    loop = asyncio.get_event_loop()

    def _convert():
        proc = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
                "-c:a", "libopus", "-b:a", "48k", "-application", "voip",
                "-f", "ogg", "pipe:1",
            ],
            input=mp3_bytes,
            capture_output=True,
            check=True,
        )
        return proc.stdout

    ogg_bytes = await loop.run_in_executor(None, _convert)
    log.info(f"  ffmpeg mp3→ogg/opus {len(ogg_bytes)} bytes")
    return ogg_bytes


# ---------- FastAPI ----------
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("voice-bridge HTTP 启动，预热 SenseVoice...")
    asyncio.create_task(get_model())
    yield
    log.info("voice-bridge HTTP 关闭")


app = FastAPI(lifespan=lifespan)


class TranscribeFileReq(BaseModel):
    path: str


class TranscribeTelegramReq(BaseModel):
    file_id: str
    bot_token: Optional[str] = ""


class SynthesizeReq(BaseModel):
    text: str
    voice_id: str
    emotion: Optional[str] = "NEUTRAL"
    instruct: Optional[str] = ""
    model: Optional[str] = FISH_MODEL_DEFAULT


class SendVoiceReq(BaseModel):
    """TTS + Telegram sendVoice 一体化端点 —— 绕开 Bun fetch 对 multipart+proxy 的 bug"""
    bot_token: str
    chat_id: str
    text: str
    voice_id: str
    emotion: Optional[str] = "NEUTRAL"
    instruct: Optional[str] = ""
    model: Optional[str] = FISH_MODEL_DEFAULT
    reply_to_message_id: Optional[int] = None


class SendFileReq(BaseModel):
    """Telegram sendPhoto / sendDocument —— 绕开 Bun fetch 对 multipart+proxy 的 bug"""
    bot_token: str
    chat_id: str
    file_path: str
    kind: str  # "photo" | "document"
    caption: Optional[str] = None
    reply_to_message_id: Optional[int] = None


@app.get("/health")
async def health():
    return {"ok": True, "model_loaded": _model is not None}


@app.post("/transcribe_file")
async def api_transcribe_file(req: TranscribeFileReq):
    try:
        return await transcribe_file(req.path)
    except Exception as e:
        log.exception("transcribe_file 失败")
        raise HTTPException(500, str(e))


@app.post("/transcribe_telegram")
async def api_transcribe_telegram(req: TranscribeTelegramReq):
    try:
        return await transcribe_telegram(req.file_id, req.bot_token or "")
    except Exception as e:
        log.exception("transcribe_telegram 失败")
        raise HTTPException(500, str(e))


@app.post("/synthesize_voice")
async def api_synthesize(req: SynthesizeReq):
    try:
        audio = await synthesize_voice(
            req.text, req.voice_id, req.emotion or "NEUTRAL",
            req.instruct or "", req.model or FISH_MODEL_DEFAULT,
        )
        return Response(content=audio, media_type="audio/ogg")
    except Exception as e:
        log.exception("synthesize_voice 失败")
        raise HTTPException(500, str(e))


@app.post("/send_voice")
async def api_send_voice(req: SendVoiceReq):
    """TTS + Telegram sendVoice（绕开 Bun fetch 的 multipart+proxy bug）"""
    import httpx
    try:
        ogg = await synthesize_voice(
            req.text, req.voice_id, req.emotion or "NEUTRAL",
            req.instruct or "", req.model or FISH_MODEL_DEFAULT,
        )
        t0 = time.time()
        # httpx 自动读取 HTTPS_PROXY / HTTP_PROXY / NO_PROXY 环境变量
        async with httpx.AsyncClient(timeout=30.0, trust_env=True) as client:
            files = {"voice": ("voice.ogg", ogg, "audio/ogg")}
            data: dict[str, Any] = {"chat_id": str(req.chat_id)}
            if req.reply_to_message_id:
                data["reply_parameters"] = json.dumps({"message_id": req.reply_to_message_id})
            r = await client.post(
                f"https://api.telegram.org/bot{req.bot_token}/sendVoice",
                files=files, data=data,
            )
        tg_ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            log.error(f"Telegram sendVoice {r.status_code}: {r.text[:200]}")
            raise HTTPException(502, f"Telegram {r.status_code}: {r.text[:200]}")
        resp = r.json()
        if not resp.get("ok"):
            raise HTTPException(502, f"Telegram: {resp}")
        msg_id = resp["result"]["message_id"]
        log.info(f"  Telegram sendVoice OK msg_id={msg_id}, {tg_ms}ms")
        return {"message_id": msg_id}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("send_voice 失败")
        raise HTTPException(500, str(e))


@app.post("/send_file")
async def api_send_file(req: SendFileReq):
    """Telegram sendPhoto / sendDocument（绕开 Bun fetch multipart+proxy bug）"""
    import httpx
    if req.kind not in ("photo", "document"):
        raise HTTPException(400, f"kind must be photo or document, got {req.kind}")
    fp = Path(req.file_path)
    if not fp.exists():
        raise HTTPException(404, f"file not found: {req.file_path}")
    field = "photo" if req.kind == "photo" else "document"
    method = "sendPhoto" if req.kind == "photo" else "sendDocument"
    ext = fp.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".mp4": "video/mp4",
        ".pdf": "application/pdf",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    try:
        t0 = time.time()
        size = fp.stat().st_size
        with open(fp, "rb") as fh:
            payload = fh.read()
        # 大文件流式上传需要单独一条 Transfer-Encoding；Telegram 50MB 以内一次性上传足够
        async with httpx.AsyncClient(timeout=120.0, trust_env=True) as client:
            files = {field: (fp.name, payload, mime)}
            data: dict[str, Any] = {"chat_id": str(req.chat_id)}
            if req.caption:
                data["caption"] = req.caption
            if req.reply_to_message_id:
                data["reply_parameters"] = json.dumps({"message_id": req.reply_to_message_id})
            r = await client.post(
                f"https://api.telegram.org/bot{req.bot_token}/{method}",
                files=files, data=data,
            )
        tg_ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            log.error(f"Telegram {method} {r.status_code}: {r.text[:200]}")
            raise HTTPException(502, f"Telegram {r.status_code}: {r.text[:200]}")
        resp = r.json()
        if not resp.get("ok"):
            raise HTTPException(502, f"Telegram: {resp}")
        msg_id = resp["result"]["message_id"]
        log.info(f"  Telegram {method} OK msg_id={msg_id}, {size} bytes, {tg_ms}ms")
        return {"message_id": msg_id}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("send_file 失败")
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7788, log_level="warning")

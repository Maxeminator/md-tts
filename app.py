"""Obsidian -> mp3. Загружаешь заметки, слушаешь с телефона."""
import asyncio
import io
import json
import re
import socket
import uuid
import zipfile
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import edge_tts
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from md_clean import clean_markdown

BASE = Path(__file__).parent
DATA = BASE / "data"
AUDIO = DATA / "audio"
TEXT = DATA / "text"
LIB = DATA / "library.json"
for d in (AUDIO, TEXT):
    d.mkdir(parents=True, exist_ok=True)

VOICES = {
    "ru-RU-SvetlanaNeural": "Светлана (ру, женский)",
    "ru-RU-DmitryNeural": "Дмитрий (ру, мужской, бывает нестабилен)",
    "en-US-AndrewMultilingualNeural": "Andrew (en, multilingual)",
    "en-US-AvaMultilingualNeural": "Ava (en, multilingual)",
    "en-GB-RyanNeural": "Ryan (en-GB)",
    "uk-UA-OstapNeural": "Остап (укр)",
}
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
FALLBACK_VOICE = "ru-RU-SvetlanaNeural"
ATTEMPTS = 2
MAX_PARALLEL = 3

app = FastAPI(title="Obsidian TTS")
app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
_lock = asyncio.Lock()
_sem = asyncio.Semaphore(MAX_PARALLEL)
_tasks: set[asyncio.Task] = set()


def load_lib() -> list[dict]:
    if LIB.exists():
        return json.loads(LIB.read_text(encoding="utf-8"))
    return []


def save_lib(items: list[dict]) -> None:
    LIB.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


async def update_item(item_id: str, **fields) -> None:
    async with _lock:
        items = load_lib()
        for it in items:
            if it["id"] == item_id:
                it.update(fields)
        save_lib(items)


async def synth(item_id: str, text: str, voice: str, rate: str) -> None:
    """Озвучка с повторами; если голос молчит (бывает у сервиса) — запасной голос."""
    out = AUDIO / f"{item_id}.mp3"
    plan = [voice] * ATTEMPTS
    if voice != FALLBACK_VOICE:
        plan += [FALLBACK_VOICE] * ATTEMPTS
    async with _sem:
        await update_item(item_id, status="processing")
        last_err = "unknown"
        for v in plan:
            try:
                comm = edge_tts.Communicate(text, v, rate=rate)
                await comm.save(str(out))
                if out.stat().st_size > 0:
                    note = None if v == voice else f"голос {voice} не ответил, использован {v}"
                    await update_item(item_id, status="done", size=out.stat().st_size, voice_used=v, note=note)
                    return
                last_err = "empty audio"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:300]
            await asyncio.sleep(1)
        out.unlink(missing_ok=True)
        await update_item(item_id, status="error", error=last_err)


def schedule(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def title_from(name: str, md: str) -> str:
    m = re.search(r"^title:\s*(.+)$", md[:2000], flags=re.M)
    if m:
        return m.group(1).strip().strip("\"'")
    return Path(name).stem


def collect_notes(upload_name: str, raw: bytes) -> list[tuple[str, str]]:
    """Возвращает [(имя, markdown)] из .md или .zip."""
    if upload_name.lower().endswith(".zip"):
        notes = []
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".md"):
                    continue
                if "/.obsidian/" in info.filename or info.filename.startswith(".obsidian/"):
                    continue
                if "/.trash/" in info.filename or info.filename.startswith(".trash/"):
                    continue
                if info.file_size > 5_000_000:
                    continue
                notes.append((info.filename, z.read(info).decode("utf-8", "replace")))
        return notes
    return [(upload_name, raw.decode("utf-8", "replace"))]


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (BASE / "templates" / "index.html").read_text(encoding="utf-8")
    opts = "".join(
        f'<option value="{k}"{" selected" if k == DEFAULT_VOICE else ""}>{v}</option>'
        for k, v in VOICES.items()
    )
    return html.replace("{{VOICE_OPTIONS}}", opts)


@app.get("/api/items")
async def api_items():
    items = load_lib()
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


@app.post("/api/upload")
async def api_upload(
    files: list[UploadFile] = File(...),
    voice: str = Form(DEFAULT_VOICE),
    rate: int = Form(0),
    say_title: bool = Form(True),
):
    if voice not in VOICES:
        voice = DEFAULT_VOICE
    rate = max(-50, min(100, rate))
    rate_s = f"{rate:+d}%"
    created = []
    for f in files:
        raw = await f.read()
        for name, md in collect_notes(f.filename or "note.md", raw):
            text = clean_markdown(md)
            if not text.strip():
                continue
            title = title_from(name, md)
            if say_title:
                text = f"{title}.\n\n{text}"
            item_id = uuid.uuid4().hex[:12]
            (TEXT / f"{item_id}.txt").write_text(text, encoding="utf-8")
            item = {
                "id": item_id,
                "title": title,
                "source": name,
                "voice": voice,
                "rate": rate_s,
                "chars": len(text),
                "created": datetime.now(timezone.utc).isoformat(),
                "status": "queued",
            }
            async with _lock:
                items = load_lib()
                items.append(item)
                save_lib(items)
            schedule(synth(item_id, text, voice, rate_s))
            created.append(item)
    return {"created": len(created)}


@app.post("/api/retry/{item_id}")
async def api_retry(item_id: str):
    items = load_lib()
    it = next((x for x in items if x["id"] == item_id), None)
    if not it:
        return JSONResponse({"error": "not found"}, 404)
    text = (TEXT / f"{item_id}.txt").read_text(encoding="utf-8")
    await update_item(item_id, status="queued", error=None)
    schedule(synth(item_id, text, it["voice"], it["rate"]))
    return {"ok": True}


@app.delete("/api/items/{item_id}")
async def api_delete(item_id: str):
    async with _lock:
        items = [x for x in load_lib() if x["id"] != item_id]
        save_lib(items)
    for p in (AUDIO / f"{item_id}.mp3", TEXT / f"{item_id}.txt"):
        p.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/text/{item_id}")
async def get_text(item_id: str):
    p = TEXT / f"{item_id}.txt"
    if not p.exists():
        return Response("not found", 404)
    return Response(p.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")


@app.get("/download/{item_id}")
async def download(item_id: str):
    it = next((x for x in load_lib() if x["id"] == item_id), None)
    p = AUDIO / f"{item_id}.mp3"
    if not it or not p.exists():
        return Response("not found", 404)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", it["title"]) or item_id
    return FileResponse(p, media_type="audio/mpeg", filename=f"{safe}.mp3")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@app.get("/feed.xml")
async def feed(request: Request):
    """RSS-подкаст: подпишись в AntennaPod / Apple Podcasts по этому URL."""
    base = str(request.base_url).rstrip("/")
    items = [x for x in load_lib() if x.get("status") == "done"]
    items.sort(key=lambda x: x["created"], reverse=True)

    entries = []
    for it in items:
        dt = datetime.fromisoformat(it["created"])
        entries.append(
            "  <item>\n"
            f"    <title>{_esc(it['title'])}</title>\n"
            f"    <guid isPermaLink=\"false\">{it['id']}</guid>\n"
            f"    <pubDate>{format_datetime(dt)}</pubDate>\n"
            f"    <enclosure url=\"{base}/audio/{it['id']}.mp3\" length=\"{it.get('size', 0)}\" type=\"audio/mpeg\"/>\n"
            f"    <description>{_esc(it['source'])} · {it['voice']}</description>\n"
            "  </item>\n"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">\n'
        "<channel>\n"
        "  <title>Мои заметки (Obsidian TTS)</title>\n"
        f"  <link>{base}/</link>\n"
        "  <description>Озвученные заметки</description>\n"
        "  <language>ru</language>\n"
        + "".join(entries)
        + "</channel>\n</rss>\n"
    )
    return Response(xml, media_type="application/rss+xml; charset=utf-8")


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    import uvicorn

    ip = lan_ip()
    print("\n  Obsidian TTS")
    print("  На компе:    http://127.0.0.1:8000")
    print(f"  С телефона:  http://{ip}:8000   (та же Wi-Fi сеть)")
    print(f"  Подкаст-фид: http://{ip}:8000/feed.xml\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

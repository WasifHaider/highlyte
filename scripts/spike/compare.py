"""Spike (throwaway): compare caption paths on real Hindi/Urdu podcasts.

Paths, per 60s chunk of each audio file in data/spike/:
  old    Groq Whisper language="en" + the Roman seed prompt (today's code)
  hi     Groq Whisper language="hi" -> glossary -> romanize Indic tokens
         -> spelling list -> constrained LLM cleanup
  ur     Groq Whisper language="ur" -> romanize (Urdu files only)

Steps are cached in data/spike/out/, so reruns only redo what changed:
  python compare.py asr       # Groq calls (cached per chunk and path)
  python compare.py build     # romanize + cleanup + HTML report

Not production code: nothing in backend/ imports this.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "data" / "spike"
OUT = SPIKE / "out"
CHUNK_S = 60

VIDEOS = {
    "Sfxub7uNchk": "hindi",
    "PCcoly7EHgU": "hindi",
    "aAPVlS2o2FI": "urdu",
    "X_z0JPkEX4k": "urdu",
}

WHISPER_MODEL = "whisper-large-v3"
CLEANUP_MODEL = "openai/gpt-oss-20b"
SEED = (
    "Yeh podcast Roman Urdu aur Hindi mein baat karta hai, jaise "
    "'mujhe yeh cheez bohat pasand hai' ya 'hum log kal milenge'. "
    "Kabhi kabhi English words bhi beech mein aa jate hain, jaise "
    "'that's actually a great point' ya 'I totally agree with you'. "
    "Log apni baat normal tareeke se karte hain, bina kisi script ke, "
    "sirf Roman letters mein."
)

# English loanwords Whisper writes in Devanagari: freeze them before
# romanizing, so they come out as the English word.
GLOSSARY = {
    "यूट्यूब": "YouTube", "वीडियो": "video", "वीडियोज़": "videos", "अपलोड": "upload",
    "सब्सक्राइब": "subscribe", "इंस्टाग्राम": "Instagram", "चैनल": "channel",
    "पॉडकास्ट": "podcast", "फ़ोन": "phone", "फोन": "phone", "म्यूज़िक": "music",
    "म्यूजिक": "music", "सूफ़ी": "Sufi", "सूफी": "Sufi", "यूनिवर्सिटी": "university",
    "डिग्री": "degree", "जॉब": "job", "जॉब्स": "jobs", "पाकिस्तान": "Pakistan",
    "इंडिया": "India", "सोशल": "social", "मीडिया": "media", "कॉलेज": "college",
    "स्कूल": "school", "स्टूडेंट": "student", "स्टूडेंट्स": "students",
    "एक्चुअली": "actually", "बेसिकली": "basically", "लिटरली": "literally",
    "ओके": "okay", "सॉरी": "sorry", "थैंक": "thank", "यू": "you",
    "प्रॉब्लम": "problem", "सिस्टम": "system", "एजुकेशन": "education",
    "सऊदी": "Saudi", "यमन": "Yemen", "अमेरिका": "America", "ईरान": "Iran",
}

# Fixed Roman spellings after romanizing: chat-style forms both Indian and
# Pakistani readers recognise, and nukta sounds Whisper tends to drop.
SPELLING = {
    "mem": "mein", "mein": "mein", "nahim": "nahi", "nahin": "nahi", "nahim.": "nahi.",
    "ham": "hum", "tum": "tum", "yah": "ye", "yeh": "ye", "vah": "woh", "vo": "woh",
    "ve": "woh", "kyomki": "kyunki", "kyonki": "kyunki", "thik": "theek",
    "maim": "main", "haim": "hain", "hum": "hum", "yar": "yaar", "bhi": "bhi",
    "kya": "kya", "kyom": "kyun", "kaun": "kaun", "jindagi": "zindagi",
    "jyada": "zyada", "jyadaa": "zyada", "khvahish": "khwahish", "khvaish": "khwahish",
    "jarur": "zaroor", "jaruri": "zaroori", "pharak": "farq", "phark": "farq",
    "farqa": "farq", "hamem": "humein", "tumhem": "tumhein", "unhem": "unhein",
    "apne": "apne", "sath": "saath", "bat": "baat", "log": "log", "hae": "hai",
    "chahie": "chahiye", "lie": "liye", "gae": "gaye", "ae": "aaye",
}

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
ARABIC = re.compile(r"[؀-ۿ]")


def groq() -> OpenAI:
    key = os.environ.get("GROQ_KEY")
    if not key:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("GROQ_KEY missing")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")


def chunks_for(video_id: str) -> list[Path]:
    src = next(SPIKE.glob(f"{video_id}.m4a"), None) or next(SPIKE.glob(f"{video_id}.*"))
    cdir = OUT / video_id / "chunks"
    if not cdir.exists():
        cdir.mkdir(parents=True)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
             "-af", "loudnorm", "-f", "segment", "-segment_time", str(CHUNK_S),
             str(cdir / "%03d.wav")],
            check=True,
        )
    # ffmpeg can leave a near-empty tail segment; Groq rejects it.
    for wav in cdir.glob("*.wav"):
        if wav.stat().st_size < 32_000:  # under ~1s of 16kHz mono
            wav.unlink()
    return sorted(cdir.glob("*.wav"))


def transcribe(client: OpenAI, wav: Path, path: str) -> dict:
    kwargs: dict = dict(model=WHISPER_MODEL, response_format="verbose_json",
                        timestamp_granularities=["word", "segment"])
    if path == "old":
        kwargs.update(language="en", prompt=SEED)
    else:
        kwargs.update(language=path)
    for attempt in range(8):
        try:
            with open(wav, "rb") as f:
                resp = client.audio.transcriptions.create(file=f, **kwargs)
            return resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        except Exception as exc:  # rate limits: back off and retry
            if type(exc).__name__ == "BadRequestError":
                raise
            wait = 20 * (attempt + 1)
            print(f"  {wav.name} {path}: {type(exc).__name__}, retry in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"gave up on {wav} {path}")


def run_asr() -> None:
    client = groq()
    for vid, lang in VIDEOS.items():
        paths = ["old", "hi"] + (["ur"] if lang == "urdu" else [])
        for wav in chunks_for(vid):
            for p in paths:
                dst = OUT / vid / f"{wav.stem}.{p}.json"
                if dst.exists():
                    continue
                dst.write_text(json.dumps(transcribe(client, wav, p), ensure_ascii=False),
                               encoding="utf-8")
                print(f"{vid} {wav.stem} {p} ok", flush=True)


# ---- script layer -------------------------------------------------------

def romanize_devanagari(token: str) -> str:
    from aksharamukha import transliterate
    core = token.strip("।,.?!\"'")
    if core in GLOSSARY:
        return token.replace(core, GLOSSARY[core])
    roman = transliterate.process("Devanagari", "RomanColloquial", token,
                                  pre_options=["RemoveSchwaHindi"])
    return roman


def romanize_urdu(token: str) -> str:
    from aksharamukha import transliterate
    return transliterate.process("Urdu", "RomanColloquial", token)


def spell(word: str) -> str:
    m = re.match(r"^(\W*)(.*?)(\W*)$", word)
    pre, core, post = m.groups()
    fixed = SPELLING.get(core.lower(), core)
    return pre + fixed + post


def script_layer(text: str, script: str) -> tuple[str, int]:
    """Token by token: Latin/num pass through, only Indic tokens romanize."""
    out, indic = [], 0
    for tok in text.split():
        if script == "hi" and DEVANAGARI.search(tok):
            out.append(spell(romanize_devanagari(tok)))
            indic += 1
        elif script == "ur" and ARABIC.search(tok):
            out.append(spell(romanize_urdu(tok)))
            indic += 1
        else:
            out.append(tok)
    return " ".join(out), indic


CLEANUP_PROMPT = """You edit Hinglish captions.
Keep the mix. Do not translate to English or shuddh Hindi.
Keep yaar, bhai, matlab, scene, vibe, literally, actually, basically.
Keep English words in English.
Fix spelling only: hy->hai, kia->kya, krna->karna, mjhy->mujhe, rahe the / raha tha.
Do not add or drop words. Keep the same number of words.
Return JSON: {"caption": "<the caption>"}"""


def cleanup(client: OpenAI, caption: str, cache: Path) -> tuple[str, str]:
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return d["caption"], d["status"]
    status, result = "rejected", caption
    try:
        resp = client.chat.completions.create(
            model=CLEANUP_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": CLEANUP_PROMPT},
                      {"role": "user", "content": caption}],
        )
        cand = json.loads(resp.choices[0].message.content)["caption"]
        if len(cand.split()) == len(caption.split()):
            status, result = "ok", cand
    except Exception as exc:
        status = f"error: {type(exc).__name__}"
    cache.write_text(json.dumps({"caption": result, "status": status}, ensure_ascii=False),
                     encoding="utf-8")
    return result, status


XLIT_MAP: dict[str, str] = {}


def build() -> None:
    # IndicXlit only runs on Python 3.10 (fairseq), so it is run once in
    # Docker over every Devanagari token and read back here as a lookup.
    xmap = OUT / "indicxlit_map.json"
    if xmap.exists():
        XLIT_MAP.update(json.loads(xmap.read_text(encoding="utf-8")))
    client = groq()
    rows = []
    for vid, lang in VIDEOS.items():
        for wav in sorted((OUT / vid / "chunks").glob("*.wav")):
            def load(p):
                f = OUT / vid / f"{wav.stem}.{p}.json"
                return json.loads(f.read_text(encoding="utf-8"))["text"].strip() if f.exists() else None
            old, hi_native, ur_native = load("old"), load("hi"), load("ur")
            row = {"vid": vid, "lang": lang, "chunk": int(wav.stem), "old": old,
                   "hi_native": hi_native}
            if hi_native:
                roman, _ = script_layer(hi_native, "hi")
                row["hi_roman"] = roman
                row["hi_clean"], row["hi_clean_status"] = cleanup(
                    client, roman, OUT / vid / f"{wav.stem}.hi.clean.json")
                row["hi_latin_ratio"] = round(
                    sum(1 for t in hi_native.split() if not DEVANAGARI.search(t))
                    / max(1, len(hi_native.split())), 2)
                if XLIT_MAP:
                    row["hi_xlit"] = " ".join(
                        spell(t.replace(t.strip("।,.?!\"'"),
                                        GLOSSARY.get(t.strip("।,.?!\"'"))
                                        or XLIT_MAP.get(t.strip("।,.?!\"'"), t)))
                        if DEVANAGARI.search(t) else t
                        for t in hi_native.split())
            if ur_native:
                row["ur_native"] = ur_native
                row["ur_roman"], _ = script_layer(ur_native, "ur")
            rows.append(row)
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    write_html(rows)
    print(f"{len(rows)} chunks -> {OUT / 'report.html'}")


def write_html(rows: list[dict]) -> None:
    e = lambda s: html.escape(s or "—")
    cards = []
    for r in rows:
        mm = f"{r['chunk']:02d}:00"
        cells = [
            ("A · today: en + seed prompt", r.get("old")),
            ("B · hi → romanize → spelling", r.get("hi_roman")),
            ("C · B + LLM cleanup", f"{r.get('hi_clean')}  [{r.get('hi_clean_status')}]"
             if r.get("hi_clean") else None),
        ]
        if r.get("hi_xlit"):
            cells.append(("E · hi → IndicXlit → spelling", r.get("hi_xlit")))
        if r["lang"] == "urdu":
            cells.append(("D · ur → Aksharamukha", r.get("ur_roman")))
        native = [("Whisper hi native", r.get("hi_native"))]
        if r.get("ur_native"):
            native.append(("Whisper ur native", r.get("ur_native")))
        body = "".join(f'<div class="c"><h4>{e(t)}</h4><p>{e(v)}</p></div>' for t, v in cells)
        nat = "".join(f'<div class="c n"><h4>{e(t)}</h4><p>{e(v)}</p></div>' for t, v in native)
        cards.append(
            f'<section><h3>{r["vid"]} · {r["lang"]} · chunk {mm}</h3>'
            f'<div class="g">{body}</div><details><summary>native script</summary>'
            f'<div class="g">{nat}</div></details></section>')
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Caption Path Spike</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--card:#fff;--bd:#e7e5e4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--bd:#44403c}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1300px;margin:auto}}
h1{{font-size:22px}} h3{{font-size:14px;color:var(--mut);margin:0 0 8px}}
section{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px;margin:0 0 14px}}
.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}
.c h4{{margin:0 0 4px;font-size:12px;color:var(--mut);font-weight:600}} .c p{{margin:0}}
summary{{cursor:pointer;color:var(--mut);font-size:13px;margin-top:8px}}
</style></head><body><h1>Caption path spike</h1>
<p>Same 60s chunks, four ways. Judge readability in Roman, names and numbers, English words kept English, and whether the words match what was said.</p>
{''.join(cards)}</body></html>"""
    (OUT / "report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    {"asr": run_asr, "build": build}[sys.argv[1]]()

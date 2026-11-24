"""Background music with Google Lyria 3 through OpenRouter (streamed; audio output requires it).

    python3 music.py OUT_BASENAME "prompt"      # writes OUT_BASENAME.<format> and .json (text, usage)
"""
import base64, json, os, sys, urllib.request
from llm import api_key, SSL, HERE

MODEL = os.environ.get("VP_MUSIC_MODEL", "google/lyria-3-pro-preview")
out, prompt = sys.argv[1], sys.argv[2]
body = {"model": MODEL, "modalities": ["text", "audio"], "stream": True, "usage": {"include": True},
        "audio": {"format": "wav"}, "messages": [{"role": "user", "content": prompt}]}
req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                             headers={"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"})
chunks, text, fmt, usage = [], [], None, None
with urllib.request.urlopen(req, context=SSL, timeout=900) as r:
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        d = json.loads(line[6:])
        if d.get("error"):
            raise SystemExit(d["error"])
        usage = d.get("usage") or usage
        for ch in d.get("choices", []):
            delta = ch.get("delta", {})
            if delta.get("content"):
                text.append(delta["content"])
            a = delta.get("audio") or {}
            if a.get("data"):
                chunks.append(a["data"])
            fmt = a.get("format") or fmt
            if a.get("transcript"):
                text.append(a["transcript"])
audio = b"".join(base64.b64decode(c) for c in chunks)
ext = fmt or ("wav" if audio[:4] == b"RIFF" else "mp3")
open(f"{out}.{ext}", "wb").write(audio)
json.dump({"model": MODEL, "prompt": prompt, "text": "".join(text), "usage": usage}, open(f"{out}.json", "w"), indent=1)
print(f"{len(audio)} bytes of {ext}; cost {usage and usage.get('cost')}; {''.join(text)[:200]}")

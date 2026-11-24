"""Narration with Google Cloud Text-to-Speech (Chirp 3 HD voices), fitted to the video's timing.

    python3 tts_google.py sample VOICE [VOICE ...]   # the first two steps in each voice, one MP3 to listen to
    python3 tts_google.py narrate VOICE              # every step, fitted to its slot: runs/audio_<voice>/

The steps' lengths are already baked into both renders, so a line that runs longer than its
slot is re-synthesised faster, never the other way round. Uses the gcloud login's token.
"""
import base64, json, os, ssl, subprocess, sys, urllib.request
from llm import HERE

PROJECT = os.environ["VP_GCP_PROJECT"]
SSL = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
proc = json.load(open(os.path.join(HERE, "runs", "procedure.json")))
timing = json.load(open(os.path.join(HERE, "runs", "timing.json")))


def synth(text, voice, path, rate=1.0, encoding="LINEAR16"):
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    lang = "-".join(voice.split("-")[:2])
    body = {"input": {"text": text}, "voice": {"languageCode": lang, "name": voice},
            "audioConfig": {"audioEncoding": encoding, "sampleRateHertz": 24000, "speakingRate": rate}}
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + token, "x-goog-user-project": PROJECT, "Content-Type": "application/json"})
    audio = base64.b64decode(json.load(urllib.request.urlopen(req, context=SSL, timeout=120))["audioContent"])
    open(path, "wb").write(audio)


def seconds(path):
    out = subprocess.run(["afinfo", path], capture_output=True, text=True).stdout
    return float(out.split("estimated duration: ")[1].split()[0])


def sample(voices):
    d = os.path.join(HERE, "runs", "voice-samples"); os.makedirs(d, exist_ok=True)
    parts = []
    for v in voices:
        short = v.split("-")[-1]
        text = f"This is {short}. " + " ".join(s["narration"] for s in proc["steps"][:2])
        p = os.path.join(d, f"{short}.wav"); synth(text, v, p); parts.append(p)
        print(f"  {v}: {seconds(p):.1f} s")
    # join with afconvert-free concatenation: raw PCM of the WAVs (same format), one header
    import wave
    out = os.path.join(d, "compare.wav")
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        for p in parts:
            with wave.open(p) as r:
                w.writeframes(r.readframes(r.getnframes())); w.writeframes(b"\0\0" * 24000)
    print("wrote", out)


def narrate(voice):
    short = voice.split("-")[-1]
    d = os.path.join(HERE, "runs", f"audio_{short}"); os.makedirs(d, exist_ok=True)
    gap = timing["gap"]
    for i, (s, t) in enumerate(zip(proc["steps"], timing["steps"]), 1):
        p = os.path.join(d, f"step_{i:02d}.wav")
        slot = t["length"] - 0.25  # the narration starts with the step and may run to just before the next
        synth(s["narration"], voice, p)
        dur = seconds(p); rate = 1.0
        if dur > slot:
            rate = round(min(1.35, dur / slot * 1.02), 3)
            synth(s["narration"], voice, p, rate=rate); dur = seconds(p)
        print(f"  step {i}: {dur:.2f} s of {slot:.2f} s{'' if rate == 1.0 else f' (rate {rate})'}{'  TOO LONG' if dur > slot + 0.05 else ''}")
    print("wrote", d)


if __name__ == "__main__":
    (sample if sys.argv[1] == "sample" else lambda v: narrate(v[0]))(sys.argv[2:])


def narrate_and_time(voice, proc_name, timing_name, audio_name):
    """A new procedure: narrate each step at the voice's natural pace and derive the timing from it."""
    p = json.load(open(os.path.join(HERE, "runs", proc_name)))
    d = os.path.join(HERE, "runs", audio_name); os.makedirs(d, exist_ok=True)
    t, steps = 3.0, []
    for i, s in enumerate(p["steps"], 1):
        path = os.path.join(d, f"step_{i:02d}.wav"); synth(s["narration"], voice, path)
        dur = seconds(path)
        length = round(max(float(s.get("min_seconds", 3)), dur + 1.0), 3)
        steps.append({"start": round(t, 3), "length": length, "audio": os.path.relpath(path, HERE), "audio_seconds": dur}); t += length
        print(f"  step {i}: {dur:.2f} s narration, {length:.2f} s step")
    json.dump({"fps": 24, "title_seconds": 3.0, "gap": 0.5, "total": round(t, 3), "steps": steps}, open(os.path.join(HERE, "runs", timing_name), "w"), indent=1)
    print(f"  total {t:.1f} s")

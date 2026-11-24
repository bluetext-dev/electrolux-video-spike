"""Stage 3a: a voice for every step, and the timing that follows from it.

    python3 narrate.py

macOS `say` stands in for a real text-to-speech service (Azure Speech in the proposal).
Writes runs/audio/step_NN.aiff and runs/timing.json: each step's start and length in seconds.
"""
import json, os, re, subprocess
from llm import HERE

FPS = 24
VOICE = os.environ.get("VP_VOICE", "Samantha")
TITLE_SECONDS = 3.0
GAP = 0.5

proc = json.load(open(os.path.join(HERE, "runs", "procedure.json")))
adir = os.path.join(HERE, "runs", "audio")
os.makedirs(adir, exist_ok=True)
t = TITLE_SECONDS
steps = []
for i, s in enumerate(proc["steps"], 1):
    path = os.path.join(adir, f"step_{i:02d}.aiff")
    subprocess.run(["say", "-v", VOICE, "-r", "175", "-o", path, s["narration"]], check=True)
    info = subprocess.run(["afinfo", path], capture_output=True, text=True).stdout
    dur = float(re.search(r"estimated duration: ([\d.]+)", info).group(1))
    length = max(float(s.get("min_seconds", 3)), dur + 2 * GAP)
    steps.append({"start": round(t, 3), "length": round(length, 3), "audio": path, "audio_seconds": dur})
    t += length
timing = {"fps": FPS, "title_seconds": TITLE_SECONDS, "gap": GAP, "total": round(t, 3), "steps": steps}
json.dump(timing, open(os.path.join(HERE, "runs", "timing.json"), "w"), indent=1)
print(f"  {len(steps)} steps, {t:.1f} s")

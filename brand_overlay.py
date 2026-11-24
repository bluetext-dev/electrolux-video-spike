"""The brand layer as transparent overlays, for renderers that don't draw it themselves (Unreal).

    python3 brand_overlay.py OUTDIR
Writes title.png and step_NN.png (1280x720, transparent), and overlays.json with when each shows.
Same design as video.py: a navy bar, an accent rule, white text, the step number in the accent colour.
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont
from llm import HERE

W, H = 1280, 720
NAVY, ACCENT, WHITE = (4, 30, 65, 240), (13, 115, 255, 255), (255, 255, 255, 255)  # navy: the logo's #041E41
FONT = "/System/Library/Fonts/Helvetica.ttc"
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
proc = json.load(open(os.path.join(HERE, "runs", os.environ.get("VP_PROC", "procedure.json"))))
timing = json.load(open(os.path.join(HERE, "runs", os.environ.get("VP_TIMING", "timing.json"))))
font = lambda px: ImageFont.truetype(FONT, px)

im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
d.rectangle([0, 290, W, 470], fill=NAVY); d.rectangle([40, 290, 50, 470], fill=ACCENT)
d.text((80, 318), proc["title"], font=font(56), fill=WHITE)
d.text((80, 400), proc.get("subtitle", ""), font=font(28), fill=WHITE)
im.save(os.path.join(out, "title.png"))
shows = [{"file": "title.png", "from": 0.0, "to": timing["title_seconds"]}]
for i, (s, t) in enumerate(zip(proc["steps"], timing["steps"]), 1):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle([0, 610, W, 680], fill=NAVY); d.rectangle([40, 610, 50, 680], fill=ACCENT)
    d.text((72, 626), str(i), font=font(34), fill=ACCENT)
    d.text((120, 628), s["caption"], font=font(32), fill=WHITE)
    name = f"step_{i:02d}.png"; im.save(os.path.join(out, name))
    shows.append({"file": name, "from": t["start"], "to": t["start"] + t["length"], "audio": os.path.basename(t["audio"]), "audio_at": t["start"]})
json.dump(shows, open(os.path.join(out, "overlays.json"), "w"), indent=1)
print(f"{len(shows)} overlays")

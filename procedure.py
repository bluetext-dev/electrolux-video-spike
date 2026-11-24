"""Stage 2: gpt-6-astra writes the procedure as data the video template can play.

    python3 procedure.py runs/model/check_vN-parts.json

Astra sees the photos of the filter hatch and the model's parts, and returns steps: narration,
a short caption, which parts move and how far, what to highlight, and where the camera looks.
It can only name parts that exist; the template refuses anything else.
"""
import json, os, sys
from llm import ask, code_block, image_part, HERE

PRODUCT = json.load(open(os.path.join(HERE, "product.json")))
TOPIC = os.environ.get("VP_TOPIC", "How to clean the drain pump filter")
EXTRA = os.environ.get("VP_PROC_EXTRA", "")
OUTNAME = os.environ.get("VP_PROC_OUT", "procedure.json")

SYSTEM = """You write the step script for a short instructional video about one real appliance.
A fixed template animates and renders it; you only decide what happens, in which order, and what is said.

Reply with one ```json block:
{
 "title": "...", "subtitle": "<product name and model>",
 "steps": [
  {"caption": "<max 7 words, shown on screen>",
   "narration": "<one or two plain sentences, read aloud; observable terms, no jargon>",
   "shot": {"target": "<part name, or 'Machine' for the whole appliance>", "distance": <metres from the target, 0.5-2.5>,
            "azimuth": <degrees around the machine, 0 = straight in front, positive = to the viewer's right>, "elevation": <degrees, 0-45>},
   "actions": [{"part": "<moving part name>", "to": <0..1, where the part should end up: 1 = fully open or removed, 0 = closed or back in place>}],
   "highlight": "<part name or null>",
   "effects": [<zero or more of the effects below, in the order they happen within the step>],
   "min_seconds": <2-6>}
 ]
}
Effects the template can draw (it builds the objects itself: a shallow plastic container on the floor under the
lowered drain guide, the water, and small debris inside the pump filter's basket):
  {"container": "place"}        the container slides in under the drain guide
  {"container": "out"}          the container is taken away to be emptied (its water goes with it)
  {"container": "back"}         the emptied container is put back under the guide
  {"water": "flow"}             water runs from the guide into the container; {"water": "trickle"} a thin last run;
  {"water": "stop"}             the water stops
  {"level": <0..1>}             the water in the container rises (or falls) to this fraction of full during the step
  {"debris": "remove"}          the debris (a coin, a hair clip, lint) is lifted out of the filter basket and put aside
Rules:
- Only name parts listed in the parts file. Only parts with a "motion" can appear in "actions".
- Start with the whole machine, then safety (unplug; towel and shallow container ready; water may run out),
  then the procedure, then putting everything back and closing up, then a short closing shot of the whole machine.
- 7 to 10 steps. Keep narration short: the whole video should be 45 to 70 seconds.
- Be correct for this machine. Where the photos cannot tell you something (such as an emergency drain hose),
  leave it out rather than guess."""


def main(parts_path):
    parts = json.load(open(parts_path))
    photos = [os.path.join(HERE, "photos", p) for p in ("01.jpg", "07.jpg", "08.jpg")]
    content = [{"type": "text", "text": f"{EXTRA}\n\nTopic: {TOPIC}\nAppliance: {PRODUCT['name']}, model {PRODUCT['model']}.\n{PRODUCT['notes']}\n\nThe model's parts:\n{json.dumps(parts['parts'], indent=1)}\n\nPhotos: the front, the filter hatch opened with the filter in place, and the filter being removed."}]
    content += [image_part(p) for p in photos]
    reply = ask("procedure", SYSTEM, content, max_tokens=16000)
    proc = json.loads(code_block(reply, "json"))
    names = set(parts["parts"]) | {"Machine"}
    moving = {n for n, p in parts["parts"].items() if p.get("motion")}
    for s in proc["steps"]:
        assert s["shot"]["target"] in names, f"unknown shot target {s['shot']['target']}"
        assert s.get("highlight") in names | {None}, f"unknown highlight {s['highlight']}"
        for a in s.get("actions", []):
            assert a["part"] in moving, f"{a['part']} does not move"
    out = os.path.join(HERE, "runs", OUTNAME)
    allowed = {("container", "place"), ("container", "out"), ("container", "back"), ("water", "flow"), ("water", "trickle"), ("water", "stop"), ("debris", "remove")}
    for s_ in proc["steps"]:
        for e in s_.get("effects", []):
            (k, v), = e.items()
            assert k == "level" and 0 <= float(v) <= 1 or (k, v) in allowed, f"unknown effect {e}"
    json.dump(proc, open(out, "w"), indent=1, ensure_ascii=False)
    for i, s in enumerate(proc["steps"], 1):
        print(f"  {i}. {s['caption']} — {s['narration']}")
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])

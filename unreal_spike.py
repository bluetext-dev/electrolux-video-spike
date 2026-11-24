"""The Unreal half: gpt-6-astra writes the Unreal Engine 5.8 Python that turns the same model and
procedure into a Level Sequence, and Movie Render Queue renders it on a GPU VM.

    python3 unreal_spike.py build [iterations]   # astra writes build.py; Unreal runs it; errors go back
    python3 unreal_spike.py render WIDTH HEIGHT  # Movie Render Queue, offscreen, PNG frames on the VM

The VM (GCP, one T4) holds Unreal in ~/UE and the project in ~/spike. Everything runs over ssh.
"""
import json, os, subprocess, sys
from llm import ask, code_block, image_part, HERE

VM = ["--project", os.environ["VP_GCP_PROJECT"], "--zone", os.environ.get("VP_VM_ZONE", "us-central1-a")]
NAME = os.environ.get("VP_VM_NAME", "elux-unreal-spike-2")
REMOTE = os.environ.get("VP_VM_PROJECT", "/home/peder/spike")
UE = os.environ.get("VP_VM_UE", "/home/peder/UE/Engine/Binaries/Linux")
OUT = os.path.join(HERE, "runs", "unreal")

CONTRACT = f"""You write one Python script for Unreal Engine 5.8.3 (Linux), run headless as a commandlet:
  {UE}/UnrealEditor-Cmd {REMOTE}/Spike.uproject -run=pythonscript -script={REMOTE}/build.py -unattended -nosplash -stdout -FullStdOutLogOutput
The project is empty apart from these enabled plugins: PythonScriptPlugin, EditorScriptingUtilities, SequencerScripting,
MovieRenderPipeline, Interchange (glTF import). Use only the `unreal` module and the Python standard library.

Inputs in {REMOTE}/input/:
- EW7F7649U2.glb: a washing machine exported from Blender (glTF, Y-up, metres). Every part is its own node, and every
  moving part's node origin is its pivot (hinge axis, or the centre of the filter's thread).
- parts.json: the moving parts and their motions IN BLENDER COORDINATES (Z up, metres, the machine's front faces -Y):
  {{"Door": {{"motion": {{"rotate": {{"axis": "Z", "degrees": -105}}, "translate": [x, y, z]}}, "location": [..], ...}}}}.
  Rotation is about the part's own origin; translation is in its parent's space. Convert to Unreal yourself
  (Z up, centimetres, left-handed), and check the conversion against where the glTF importer actually put things.
- procedure.json: the steps (shot target, distance in metres, azimuth in degrees where 0 = in front of the machine and
  positive = to the viewer's right, elevation in degrees; actions with "to" = the fraction of the part's full motion it
  should end at; a highlight part).
- timing.json: fps, title_seconds, and each step's start and length in seconds. The sequence runs from 0 to "total" + 1 s.

The script must:
1. Import the glb into /Game/Machine and place the machine in a new level /Game/Maps/Spike, keeping each part a separate
   actor with its pivot, and moving parts attached so that children move with their parent (the door's glass moves with the door).
2. Light a clean studio: a large light-grey floor, a SkyLight, a soft key light, fill and rim (RectLights), and exposure fixed
   (a PostProcessVolume with manual exposure), so white plastic reads white, not grey or blown out.
3. Build a LevelSequence /Game/Seq/Clean at timing.fps, bound to a CineCameraActor with a camera cut track:
   - title (0 .. title_seconds): orbit from azimuth -40 to the first step's azimuth around the machine;
   - each step: the camera moves to the step's shot during the step's first second, then holds;
   - each action: the part moves from its current fraction to "to" over two seconds starting one second into the step;
   - the highlight part, if any, glows softly during its step (an emissive material override or a material parameter keyed in the sequence).
4. Create a Movie Render Queue primary config asset /Game/Render/Config: deferred rendering, PNG output to
   {REMOTE}/frames/ with the file name format "f_{{frame_number}}", resolution read from {REMOTE}/input/render.json
   ({{"width": .., "height": ..}}), anti-aliasing with a few temporal samples, and the whole sequence range.
5. Save every asset and the level, then write {REMOTE}/build_ok.json with the names of the actors it spawned, the machine's
   bounds in Unreal units, and each moving part's pivot in Unreal units.
Print clear progress lines. Raise on any failure rather than continuing.
In this commandlet, Python DeprecationWarnings are raised as errors: use only current (5.8) API names and properties.
parts.json lists every labelled part; parts that do not move have "motion": null. Each run starts from an empty Content folder.
Reply with a short note on your approach, then the complete script in one ```python block."""


def ssh(cmd, timeout=7200):
    r = subprocess.run(["gcloud", "compute", "ssh", NAME, *VM, "--command", cmd], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def scp(src, dst):
    subprocess.run(["gcloud", "compute", "scp", *src, f"{NAME}:{dst}", *VM], stdin=subprocess.DEVNULL, check=True, capture_output=True)


def build(iterations, start=None, feedback=None, images=()):
    os.makedirs(OUT, exist_ok=True)
    runs = os.path.join(HERE, "runs")
    ssh(f"mkdir -p {REMOTE}/input {REMOTE}/frames")
    scp([os.path.join(OUT, "EW7F7649U2.glb")], f"{REMOTE}/input/EW7F7649U2.glb")
    scp([os.path.join(OUT, "EW7F7649U2-parts.json")], f"{REMOTE}/input/parts.json")
    scp([os.path.join(runs, "procedure.json"), os.path.join(runs, "timing.json")], f"{REMOTE}/input/")
    open(os.path.join(OUT, "render.json"), "w").write(json.dumps({"width": 1280, "height": 720}))
    scp([os.path.join(OUT, "render.json")], f"{REMOTE}/input/render.json")
    parts = json.load(open(os.path.join(OUT, "EW7F7649U2-parts.json")))
    moving = {k: v for k, v in parts.items() if v.get("motion")}
    brief = (f"The moving parts:\n{json.dumps(moving, indent=1)}\n\nprocedure.json:\n{open(os.path.join(runs, 'procedure.json')).read()}\n\n"
             f"timing.json:\n{open(os.path.join(runs, 'timing.json')).read()}")
    if start and feedback:
        first = int(start.split("_v")[1].split(".")[0]) + 1
        script = open(start).read()
        content = [{"type": "text", "text": f"Your script builds and renders. Frames from the render follow. {feedback}\n\n{brief}\n\nThe script:\n```python\n{script}\n```\nReply with a short list of what you change, then the complete improved script."}]
        content += [image_part(p) for p in images]
        reply = ask(f"unreal polish v{first - 1}", CONTRACT, content, max_tokens=40000)
        script = code_block(reply)
    elif start:
        first = int(start.split("_v")[1].split(".")[0]) + 1
        script = open(start).read()
        log = open(start.replace(".py", ".out")).read()
        reply = ask(f"unreal fix v{first - 1}", CONTRACT, f"Your script failed or did not write build_ok.json. The Python and error lines from Unreal's log:\n{log[-12000:]}\n\n{brief}\n\nThe script:\n```python\n{script}\n```\nReply with the complete corrected script.", max_tokens=40000)
        script = code_block(reply)
    else:
        first = 1
        reply = ask("unreal build v1", CONTRACT, brief, max_tokens=40000)
        script = code_block(reply)
    for n in range(first, first + iterations):
        path = os.path.join(OUT, f"build_v{n}.py")
        open(path, "w").write(script)
        scp([path], f"{REMOTE}/build.py")
        print(f"v{n}: running in Unreal")
        rc, log = ssh(f"rm -f {REMOTE}/build_ok.json; rm -rf {REMOTE}/Content/*; {UE}/UnrealEditor-Cmd {REMOTE}/Spike.uproject -run=pythonscript "
                      f"-script={REMOTE}/build.py -unattended -nosplash -stdout -FullStdOutLogOutput > {REMOTE}/build_v{n}.log 2>&1; "
                      f"echo rc=$?; test -f {REMOTE}/build_ok.json && cat {REMOTE}/build_ok.json; "
                      f"grep -E 'LogPython|Error|error:|Traceback' {REMOTE}/build_v{n}.log | tail -80")
        open(os.path.join(OUT, f"build_v{n}.out"), "w").write(log)
        if ssh(f"test -f {REMOTE}/build_ok.json")[0] == 0:
            print(f"v{n}: built"); return
        print(f"v{n}: failed; the log goes back to astra")
        if n == first + iterations - 1:
            return
        reply = ask(f"unreal fix v{n}", CONTRACT, f"Your script failed or did not write build_ok.json. The Python and error lines from Unreal's log:\n{log[-12000:]}\n\n{brief}\n\nThe script:\n```python\n{script}\n```\nReply with the complete corrected script.", max_tokens=40000)
        script = code_block(reply)


def render(width, height):
    open(os.path.join(OUT, "render.json"), "w").write(json.dumps({"width": width, "height": height}))
    scp([os.path.join(OUT, "render.json")], f"{REMOTE}/input/render.json")
    rc, log = ssh(f"rm -rf {REMOTE}/frames/*; cd {REMOTE}; /usr/bin/time -f 'wall %e s' {UE}/UnrealEditor {REMOTE}/Spike.uproject /Game/Maps/Spike -game "
                  f"-LevelSequence=/Game/Seq/Clean -MoviePipelineConfig=/Game/Render/Config -RenderOffScreen -windowed "
                  f"-ResX={width} -ResY={height} -NoLoadingScreen -unattended -log > {REMOTE}/render.log 2>&1; "
                  f"echo rc=$?; tail -1 {REMOTE}/render.log; ls {REMOTE}/frames | wc -l; grep -E 'Error|MovieRenderPipeline' {REMOTE}/render.log | tail -20")
    open(os.path.join(OUT, f"render_{width}.out"), "w").write(log)
    print(log[-3000:])


if __name__ == "__main__":
    if sys.argv[1] == "polish":
        frames = sorted(os.listdir(os.path.join(OUT, "sample")))
        pick = [os.path.join(OUT, "sample", frames[i]) for i in (0, 4, 10)]
        build(int(sys.argv[3]) if len(sys.argv) > 3 else 4, sys.argv[2],
              feedback="Fix exactly two things and keep everything else as it is: (1) the door glass renders opaque black; "
                       "it should be tinted, see-through glass like the product photos, where the drum behind it is visible; "
                       "(2) behind the floor there is a black band at the horizon: give the studio a seamless light-grey backdrop "
                       "(an infinity cove, or a floor large enough with a matching sky) so the background is light grey everywhere.",
              images=pick)
    elif sys.argv[1] == "build":
        build(int(sys.argv[2]) if len(sys.argv) > 2 else 4, sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        render(int(sys.argv[2]), int(sys.argv[3]))

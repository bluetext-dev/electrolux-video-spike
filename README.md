# Spike: an instructional video from product photos, with gpt-6-astra and Blender

**Question.** Can gpt-6-astra and Blender turn the public photos of a named Electrolux
appliance into an on-brand instructional video, with no CAD, no 3D scan and no 3D-generation
service, in the time a hackathon team has?

**Answer: yes.** From six retailer photos of the **Electrolux PerfectCare 700, EW7F7649U2**
and its three dimensions, astra built a recognisable, correctly proportioned model with working
moving parts. It wrote a ten-step procedure for *How to clean the drain pump filter*, and a fixed
template rendered it into a narrated one-minute MP4. Astra cost **about $2.35**. The work took about
**half an hour of machine time** on an M1 Pro laptop: 9 minutes of astra and 14 of rendering.

**The same video from Unreal Engine 5.8**, with the same model and procedure, is below in
[The Unreal half](#the-unreal-half). There, astra wrote the Unreal script itself and got it to
build on the seventh round, for $6.87. One more round of critique
fixed the backdrop and made the glass see-through, if still too dark. Unreal rendered the video in 5 minutes on a cloud T4.

## The pipeline

| Stage | Who | What | Output |
|---|---|---|---|
| 1. Model | astra, 3 rounds | Photos and dimensions in, a Blender Python script out. Blender runs it headless and renders three check views (`render_check.py`). Astra compares them with the photos and rewrites the script. | `runs/model/model_vN.py`, check renders |
| 2. Procedure | astra, 1 call | The front photo, both filter-hatch photos and the model's part list in, the steps out as JSON: caption, narration, camera shot, which parts move and how far, what to highlight. A validator refuses any part the model does not have. | `runs/procedure.json` |
| 3. Narration | macOS `say`, a stand-in for Azure Speech | One audio file per step. Each step lasts as long as its narration. | `runs/audio/`, `runs/timing.json` |
| 4. Video | our template, `video.py` | Camera moves, part motions, a pulsing highlight, a title card and a lower third with step numbers. The same code for every procedure, so on-brand is a property of the template, not of a prompt. | frames |
| 5. Encode | Blender's sequencer, `assemble.py` | Frames and narration into H.264 and AAC, with no ffmpeg installed. | `runs/final/*.mp4` |

The division of labour is the one the solution hypothesis
asks for. The model decides the words and the order. It also writes the geometry, from the
real product's photos. It does not paint pixels: every frame is a deterministic render.

## What astra did

**The model.** The first script already had the right silhouette. After one round of
critique it had these:
- a black control panel with the display and the knob;
- the door with a dark outer ring, a chrome inner ring and tinted glass;
- the ribbed side;
- the round hatch at the bottom right;
- behind the hatch, the white filter cap with its blue grip, a red emergency-drain part, and a
  blue drain guide that astra added itself from photo 07.

Version 3 has 174 objects. It has five moving parts, each with its pivot where the real hinge
or thread is:

| Part | Motion |
|---|---|
| Door | swings 105° on its hinge |
| Detergent drawer | pulls out 25 cm |
| Filter hatch | swings open 105° |
| Blue drain guide | folds down 88° |
| Pump filter | unscrews two turns and comes out 16 cm |

The check renders (`check_vN-*.png`) are in `outputs/`, and two stills from the final video are in
`stills.jpg`. The side-by-side comparisons with the photos (`compare_*.jpg`) stay
local, because they contain the retailer's photos.

**The procedure.** Ten steps:
1. The whole machine.
2. Safety: unplug, let hot water cool, have a towel and a shallow container ready.
3. Open the hatch.
4. Lower the drain guide.
5. Loosen the filter slightly and let the water drain.
6. Unscrew the filter and remove it.
7. Rinse it and wipe the seal.
8. Refit the filter clockwise.
9. Fold the guide up and close the hatch.
10. Check for leaks at the next wash.

This is the shape of the real Electrolux instruction for this series. It was **not** checked
against the service manual, which we do not have. That is exactly the `generation-accuracy`
concern in the viability concerns.

## Cost and time

| Call | Seconds | Tokens in / out | Cost |
|---|---|---|---|
| model v1 | 150 | 3,361 / 8,809 | $0.48 |
| model v2 (critique of v1) | 178 | 16,774 / 11,226 | $0.77 |
| model v3 (critique of v2) | 191 | 20,703 / 12,700 | $0.89 |
| procedure | 25 | 9,901 / 1,463 | $0.20 |
| **Total** | **9 min** | | **$2.35** |

Every call went through OpenRouter, restricted to zero-data-retention providers, and each was
served by Azure. Blender's work on the M1 Pro (16 GB):
- **Model build:** a few seconds per version.
- **Check renders:** about 55 s, mostly compiling shaders the first time.
- **Preview render:** 2.5 min, every sixth frame at 640×360.
- **Full render:** 14 min (846 s) for 1,505 frames at 1280×720 in EEVEE.
- **Encoding:** 2 min. The result is a 62.7 s MP4 of 9 MB.

## What broke, and whose it was

- **Astra, once.** Version 3 ended with a self-check that called `.length` on an Euler
  rotation, which has none. It's a one-line fix, patched by hand and marked in
  `runs/model/model_v3.py`. The loop should give the model a fix round even on its last
  iteration. It gives one on every earlier round.
- **Our template, three times, found in the preview:**
  - the captions were laid out for a wider frame than a 35 mm lens gives;
  - the navy caption bars came out light blue, because the scene lit them;
  - on close-ups the captions sat behind the machine, since they were placed 1 m in front of
    a camera that stood 0.5 m from it.

  All three are fixed in `video.py`. A cheap preview pass, every sixth frame at quarter size,
  caught all three before the full render.
- **Getting the photos.** electrolux.se and electroluxshop.se reset scripted connections, which
  looks like bot protection. The photos came from a retailer's gallery. Teams will need the
  material handed to them.

## What it means for the hackathon

1. **The capability is within a hack day.** Once the harness exists, a team gets from photos to
   a narrated video in under an hour of machine time and a few dollars of astra. The harness is
   the starter repository we promised in the brief.
2. **Blender runs headless.** Nothing here needs the Blender window or its MCP add-on: the model
   writes scripts, and Blender runs them from the command line. That fits the browser
   environment, once we have established that EEVEE renders there without a GPU. If it doesn't,
   Cycles on CPU is slower but works anywhere. **This is the next thing to spike, on the machine
   type we would give the teams.**
3. **The geometry is a likeness, not CAD.** It's right for showing *which part* and *which way
   it moves*. Nothing inside the machine is true beyond what the photos show. For repair topics
   past the hatch, the teams need Electrolux's exploded diagrams or CAD, as the
   asset routes say.
4. **Correctness needs a reviewer.** Astra's procedure is plausible and safe-sounding. Whether
   it's right for this machine is for an Electrolux service engineer to say.
5. **OpenRouter is fine for public photos only.** It has no EU-only route. Electrolux material
   goes through the environment in the brief.

## The Unreal half

**Question.** Can astra drive Unreal Engine too, and does Unreal give a clearly better picture?

**Set-up.** One GCP VM, `n1-standard-8` with an NVIDIA T4, in europe-west4-c. L4 GPUs were out of stock in every European zone. Unreal Engine 5.8.3
for Linux (37 GB) was downloaded with Peder's Epic account, onto the VM only. The model is
astra's Blender model, exported as glTF with its pivots (`export_gltf.py`). The procedure and
timing are stage 2's.

**What astra wrote.** Unlike the Blender half, where the template is ours, here astra wrote the
whole Unreal script (`unreal_spike.py` holds the contract). The script does five things:
- imports the glTF through Interchange;
- keeps every part a separate actor, with moving parts attached and pivoted;
- lights a studio;
- builds a Level Sequence with a camera cut track, per-step camera moves, part motions and
  highlights;
- creates a Movie Render Queue config.

Unreal ran it headless as a commandlet. Each failure's log went back to astra.

| Round | What stopped it |
|---|---|
| 1 | `unreal.SequenceTimeUnit` does not exist in 5.8 |
| 2 | our harness: `render.json` was not uploaded yet |
| 3 | a static part with `"motion": null` in our parts file |
| 4 | a deprecated Interchange property; this commandlet raises DeprecationWarnings as errors |
| 5 | our harness: the previous run's level was still there |
| 6 | a post-process override property, `override_camera_aperture`, that does not exist |
| 7 | **built**: 194 assets, level, sequence of 1,504 frames, render config |

Astra checked its own coordinate conversion (Blender Z-up metres to Unreal Z-up centimetres,
Y flipped) against where the importer actually placed the parts. It reported the conversion
and a **0.0 cm** calibration error in `build_ok.json`.

**Cost and time.**

| | Figure |
|---|---|
| Astra | 7 calls, 30 minutes, **$6.87** |
| Unreal per round | about 1 minute |
| Render (Movie Render Queue, offscreen, 1280×720) | **5 min 16 s** for 1,504 frames on the T4, against 14 min for Blender EEVEE on the M1 |
| Brand layer and narration | 11 transparent overlays from `brand_overlay.py`, in the same design as `video.py`, laid over the frames with ffmpeg on the VM, with the same narration |
| Result | `EW7F7649U2-clean-drain-pump-filter-unreal.mp4`, 62.6 s, 3.5 MB |

**The picture.** The choreography matches the Blender version step for step. Unreal's lighting
is better: soft contact shadows, depth, and white plastic that reads as plastic. Two defects
remain, both in astra's scene, and both fixable in another round:
- **the door glass renders black**, because the tinted-glass material did not come across as
  translucent;
- **a black horizon band**: the studio has a floor but no backdrop or sky.

See `blender-vs-unreal.jpg` and `sheet.jpg`.

**The fix round (v8–v9).** Astra got its v7 script and three rendered frames, and was told to
fix exactly those two defects. It paid for itself from Peder's personal OpenRouter workspace,
reading the key from the macOS keychain (`openrouter-personal`, in `llm.py`).

| Round | Cost | Result |
|---|---|---|
| v8 | $1.20 | failed in Unreal |
| v9 | $1.15 | built |
| Render | | 3 minutes, now that the shaders are cached |

What changed, in `v7-vs-v9.jpg` (v7 on top):
- **The horizon is fixed.** A seamless light-grey backdrop has replaced the black band.
- **The glass is only partly fixed.** It is now see-through and a drum paddle shows, but it is
  still much darker than the product photo.

**Round parts (v10, patched by hand).** In v9 every round part (the door ring, the hatch, the
filter) was drawn with straight segments, although the model has 160–192 segments per ring and
looks round in Blender. The cause: the importer builds every mesh with Nanite, and this Linux
Vulkan set-up draws each Nanite mesh's heavily reduced fallback copy instead. A few lines added
after astra's import, marked in `runs/unreal/build_v10.py`, rebuild all 174 meshes without
Nanite, and the parts render round (`v9-vs-v10.jpg`). **For the contract:** import
without Nanite, or enable shader model 6 for Vulkan, and check a close-up of a round part.

The T4 VM could not be restarted: a stockout in europe-west4-c, then in every European zone
tried. Its disk was snapshotted and the VM re-created where a GPU was free. That was an **L4 in
us-central1-a**, on the first try. The data is public photos only, so the region does not matter.
The render took 2 min 50 s on the L4.

The shared video was v10 until the voice, music and intro below were added.

**Setting the VM up, for next time.**
- The GCP image `common-cu129-ubuntu-2204-nvidia-580` ships NVIDIA's *server* driver flavour.
  Its Vulkan driver refuses to start. Installing `nvidia-driver-580-open` with the matching
  `linux-modules-nvidia-580-open-<kernel>` and rebooting fixed it.
- Ubuntu 22.04's Vulkan loader is too old for the 580 manifests. The LunarG loader,
  `libvulkan1` 1.4, replaces it.

**What it means.** Astra can drive Unreal, but Unreal's API moves faster than the model's
knowledge. Seven rounds and about 35 minutes is fine for us. A hackathon team without that
loop would spend an afternoon on it. Unreal is worth it where the look matters, such as
marketing and e-commerce video. Blender is enough for instruction. Both need a GPU to be fast,
and Unreal needs one to render at all.

## Voice, music and a branded intro

The finished film is `EW7F7649U2-care-guide-drain-pump-filter-v2.mp4`, 67 s. It is the
one behind the shared link. It is the Unreal picture with a logo intro, captions in the brand's
navy, a natural voice and a music bed.

| Layer | How | Cost |
|---|---|---|
| **Voice** | Google Cloud Text-to-Speech, Chirp 3 HD voice **Kore** (`tts_google.py`). Four voices were compared and Peder chose Kore. The steps' lengths were already baked into the renders, so each line is fitted to its slot: eight read at natural pace, step 7 at 1.14× and step 9 at 1.03×. The line may run until 0.25 s before the next step. `remix.py` and `final_mix.py` swap the sound without re-rendering. | a fraction of a cent, on the GCP credit |
| **Music** | Google **Lyria 3** through OpenRouter (`music.py`; audio output requires streaming). One prompt: calm, warm, felt piano, a swell for the logo, a steady bed, about 70 s. It returned a 71.7 s instrumental. In the mix it plays at 0.85 under the logo, then sinks over 2 s to one steady low level, 0.055, for the rest, and fades out over the last 3 s. | $0.08 |
| **Intro** | `intro.py`, deterministic Blender, 5 s. It uses the Electrolux logo from Wikimedia Commons (`brand/electrolux-logo.svg`, listed as public domain but trademarked). The emblem fades in and settles, the letters appear one by one, and a line names the guide and model. It dissolves into the video over half a second. | none |
| **Brand colour** | The logo's own navy, **#041E41**, for the intro and the caption bars. The captions were re-burned on the Unreal frames. | none |

**What broke along the way, all ours:**
- **The colour was converted twice.** The first intro gave Blender the sRGB navy as if it were
  linear, so it came out a mid blue.
- **The emblem moved.** It was parented before its pivot's matrix was up to date, so it shifted
  left.
- **The music pumped.** The first mix ducked it under each line and let it back up in every short
  pause, which sounds unstable. One steady low level works better.
- **Blender's sequencer greyed the picture.** It applies its default view transform (AgX) to
  finished frames, so white came out at 197, not 255. Setting the transform to Standard in
  `remix.py` and `final_mix.py` passes frames through unchanged (a machine-body pixel: 211 against
  the raw render's 210).
- **A stale player.** Overwriting a file QuickTime has open makes it play a stale copy. Every
  remix now gets a new file name.

**The brand.** The logo is Electrolux's trademark. Using it is fine in a spike made for Electrolux.
Anything published beyond the 7-day link needs their brand team's approval. Electrolux's own
typeface is proprietary, so the line under the logo and the captions use Arial and Helvetica.

## The room from Electrolux's own photos

Peder supplied two photos from electrolux.com of this model's family in a Scandinavian laundry
room. They are in `photos/scene-reference*.png`. The machine now
stands in that room. The film is `EW7F7649U2-care-guide-drain-pump-filter-room.mp4`.

- **Assets** (`fetch_assets.py`): CC0 from Poly Haven:
  - textures: oak veneer, marble, concrete, white plaster;
  - models: a wicker basket, a potted plant, two bottles;
  - an indoor HDRI.
- **Astra built the room** (`environment.py`) around the untouched machine, with every object
  named `Env_*` and two cameras matching the two photos. Each round rendered both views and put
  them next to the photos for critique. After the first four rounds, v5–v7 also got a reviewer's
  notes: sunlight, stone, camera 2 and the rug. v6 was the best; v7 drifted back.
  Seven rounds cost **$6.87**.
- **Hand-tuned from v6** (`runs/env/env_v8.py`, marked): paler and less orange oak, lighter
  stone, exposure 0 instead of −0.65, and camera 2 moved right. Moving it further showed the void
  beyond the set.
- **Cycles, not EEVEE.** The room's look depends on soft bounce light: EEVEE gave hard shadows,
  black glass and muddy tones (`cycles-vs-eevee.jpg`).
- **Rendering.** On this Mac, Cycles took about 100 s a frame at half size. On the L4 VM it ran
  with OptiX: Blender 5.1.2 for Linux, the scene packed into one 72 MB file, 64 samples with
  denoising. **1,504 frames at 1280×720 took 246 min**, about 10 s a frame.
- **Template changes** (`video.py`) when `Env_` objects are present:
  - it keeps the room's renderer and light and adds no studio;
  - it measures the machine without the room;
  - it pulls the whole-machine shots back 1.5× and aims them 16 cm higher, so the worktop is in
    frame;
  - it leaves the captions out and burns them on afterwards (ffmpeg on the VM), in exact
    #041E41.
- **The intro, Kore's voice and the music** are mixed on as before (`final_mix.py`).

## Water, a tray and debris (v2)

Peder's review of the room film: a glitch in front of the hatch, and the narration mentions a
container that the picture never shows. The film is now
`EW7F7649U2-care-guide-drain-pump-filter-room-v2.mp4`, 78.5 s.

- **The hatch was too low** in astra's model. Its lower edge sat at 8 mm, below the body's bottom
  edge at 17 mm, so the lower front trim ran across it. One constant, `HZ`, moved from 0.074 to
  0.099 (`runs/model/model_v3b.py`, marked), and the whole hatch assembly moved with it.
- **Astra rewrote the procedure** (`procedure_v2.json`, $0.21) with a new vocabulary of
  **effects** the template draws: the container placed, out and back; the water flowing,
  trickling and stopping; the water level; and debris removed. The sequence is: place a tray
  under the guide, loosen the filter so water runs, tighten it when the tray is nearly full,
  empty the tray and put it back, loosen for the rest, remove the filter, take the debris out,
  close up.
- **The template's effects** (`video.py`), placed from the model's own geometry:
  - a flat, open tray 2 cm high, because the lowered guide's lip is only 24 mm above the floor;
  - a water stream from the lip, with animated ripples;
  - the water in the tray, which rises, and is hidden until it starts;
  - the tray carried out of frame and back;
  - a brass coin, a red hair clip and lint in the filter basket, each lifted out, held in view
    above the filter, then put aside;
  - water tinted light blue, so it reads on camera.
- **Checking in Cycles:** EEVEE cannot show clear water, so the checks were Cycles stills
  rendered on the Mac, at 32 samples and quarter size.
- **Kore narrates the new steps** at her natural pace, and the timing follows from it
  (`runs/timing_v2.json`).
- **Rendering:** 1,775 frames on the L4 took 294 min.

## The zoom on "hatch", and real debris (v3)

The film is now `EW7F7649U2-care-guide-drain-pump-filter-room-v3.mp4`, 78.5 s.

- **The camera closes in on the hatch as it is named.** A step can now carry a `cue`: a second
  shot with a start and end time in the narration (`runs/procedure_v3.json`). For step 1 the times
  come from the narration's own loudness: the short pause before "round hatch" ends at 2.60 s, and
  the word group lasts to 3.36 s. So the camera moves from 2.55 s to 3.35 s. Synthesising the
  sentence's beginning on its own does not work for timing: it is spoken as a finished sentence,
  with a different rhythm and trailing silence.
- **The debris is hair, wet dust, a gold candy wrapper and the brass coin.** The red hair clip is
  gone. All four are lifted together and held side by side above the filter for about 1.3 s; one
  after another left each under a second, too short to see.
- **Only what changed was re-rendered.** Steps 1–2 and 7–8 (frames 72–421 and 1,152–1,442) went
  into the existing frames, because Cycles with a fixed seed renders the same frame the same way.
  That took 108 min for 640 frames, against about 5 h for the whole film.

## What is in this repository

| Path | What |
|---|---|
| `films/` | The rendered films. The latest is `EW7F7649U2-care-guide-drain-pump-filter-room-v3.mp4`; the Unreal one is `EW7F7649U2-clean-drain-pump-filter-unreal-kore.mp4`. |
| `outputs/` | The stills, check renders and comparisons this README names, and the model spend log (`usage.jsonl`). |
| `photos/` | The retailer's product photos of the EW7F7649U2 (elon.se gallery) and the two room reference photos from electrolux.com. They are Electrolux's and the retailer's, here only as the spike's input. |
| `brand/` | The Electrolux logo (Wikimedia Commons; a trademark of Electrolux). |
| `assets/` | The CC0 textures, models and HDRI from Poly Haven that the room uses (`fetch_assets.py` downloads them again). |
| `runs/model/`, `runs/env/`, `runs/unreal/` | Every script astra wrote: the model, the room and the Unreal build, version by version. |
| `runs/procedure*.json`, `runs/timing*.json` | The procedures astra wrote and the timings that follow from the narration. |
| `runs/audio/`, `runs/audio_Kore_v2/` | The narration: macOS `say` for the first procedure, Google's Kore voice for the latest. Both were generated again for this repository, so they differ by fractions of a second from the ones in the films. |
| `runs/music/bed.mp3` | The Lyria music bed. |
| `unreal-project/Spike.uproject` | An empty Unreal project with the plugins the Unreal half needs. It was written again from the plugin list and has not been opened in Unreal. |

## Run it

On macOS with Blender 5.1 in `/Applications` (or `BLENDER=/path/to/blender`), from the repository's root:

    ./make_film.sh --preview     # quarter-size frames, about 2 minutes
    ./make_film.sh               # the film with intro, narration and music: runs/final/film.mp4

That needs no key and no cloud account: it plays the model, procedure, narration and music that are
already here. It makes the studio version; the room version (`runs/env/env_v8.py`) was rendered with
Cycles on a GPU machine and is in `films/`.

To have astra do the work again, from the photos:

    export OPENROUTER_API_KEY=...        # spend is capped by VP_BUDGET_USD, default $10
    python3 model.py 3                   # stage 1, astra; keeps every version in runs/model/
    python3 procedure.py runs/model/check_v3-parts.json
    python3 narrate.py                   # macOS say; or tts_google.py with VP_GCP_PROJECT set
    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b runs/model/model_v3.blend --python video.py -- runs/procedure.json runs/timing.json runs/final
    $B -b --factory-startup --python assemble.py -- runs/final runs/timing.json runs/final/out.mp4

Blender 5.1.2. Python 3.12, standard library only; Pillow for the overlays (`requirements.txt`).
The scripts assume macOS: the Blender path, the system fonts, `say`, `afinfo` and `/etc/ssl/cert.pem`.

For the Unreal half, a Linux machine with a GPU and Unreal Engine 5.8 is needed, reached with
`gcloud compute ssh`. Set `VP_GCP_PROJECT`, `VP_VM_NAME`, `VP_VM_ZONE`, `VP_VM_PROJECT` (the folder
holding `Spike.uproject` on that machine) and `VP_VM_UE` (Unreal's `Engine/Binaries/Linux`). Then
`python3 unreal_spike.py build 5`, `python3 unreal_spike.py render 1280 720`, and
`runs/unreal/assemble.sh` on that machine. The hackathon's render machines already hold the tested
project at `~/spike`.

Rendered frames and `.blend` files are not committed; `make_film.sh` makes them.

"""The finished film: branded intro, dissolve into the video, narration, and a music bed that
ducks under the voice.

    blender -b --factory-startup --python final_mix.py -- INTRO_FRAMES_DIR PICTURE.mp4 AUDIO_DIR MUSIC runs/timing.json OUT.mp4
"""
import json, os, subprocess, sys
import bpy

intro_dir, picture, adir, music, timing_path, out = sys.argv[sys.argv.index("--") + 1:][:6]
timing = json.load(open(timing_path))
FPS = timing["fps"]
DISSOLVE = 12                                  # frames of cross-dissolve from the intro into the video
MUSIC_INTRO, MUSIC_BED = 0.85, 0.055   # full under the logo, then one steady low level: no pumping between lines
scene = bpy.context.scene
scene.render.fps = FPS
scene.view_settings.view_transform = "Standard"  # finished frames: pass them through unchanged, no second tone curve
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1280, 720, 100
se = scene.sequence_editor_create()

frames = sorted(f for f in os.listdir(intro_dir) if f.endswith(".png"))
intro = se.strips.new_image("intro", os.path.join(intro_dir, frames[0]), 1, 1)
for f in frames[1:]:
    intro.elements.append(f)
start = len(frames) - DISSOLVE + 1               # the video starts under the intro's last frames
video = se.strips.new_movie("video", picture, 2, start)
cross = se.strips.new_effect("dissolve", "CROSS", 3, start, length=DISSOLVE, input1=intro, input2=video)
offset = (start - 1) / FPS                       # seconds the whole video is shifted by

def seconds(path):
    o = subprocess.run(["afinfo", path], capture_output=True, text=True).stdout
    return float(o.split("estimated duration: ")[1].split()[0])

speech = []
files = sorted(f for f in os.listdir(adir) if f.startswith("step_"))
for i, (f, s) in enumerate(zip(files, timing["steps"]), 1):
    t0 = offset + s["start"]; p = os.path.join(adir, f)
    se.strips.new_sound(f"voice{i}", p, 4 + i % 2, int(round(t0 * FPS)) + 1)
    speech.append((t0, t0 + seconds(p)))

end = start + video.frame_final_duration - 1
scene.frame_start, scene.frame_end = 1, end
bed = se.strips.new_sound("music", music, 6, 1)
bed.frame_final_end = end + 1

def key(t, v):
    bed.volume = v; bed.keyframe_insert("volume", frame=max(1, int(round(t * FPS)) + 1))

key(0, MUSIC_INTRO); key(offset - 0.5, MUSIC_INTRO); key(offset + 1.5, MUSIC_BED)
total = end / FPS
key(total - 3.0, MUSIC_BED); key(total, 0.0)

im = scene.render.image_settings
im.media_type = "VIDEO"; im.file_format = "FFMPEG"
ff = scene.render.ffmpeg
ff.format = "MPEG4"; ff.codec = "H264"; ff.constant_rate_factor = "HIGH"; ff.audio_codec = "AAC"; ff.audio_bitrate = 192
scene.render.filepath = out
bpy.ops.render.render(animation=True)
print(f"total {total:.1f} s, video shifted {offset:.2f} s")

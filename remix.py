"""Replace a finished video's narration, keeping its picture.

    blender -b --factory-startup --python remix.py -- IN.mp4 AUDIO_DIR runs/timing.json OUT.mp4
AUDIO_DIR holds step_NN.wav (or .aiff), each placed at its step's start.
"""
import json, os, sys
import bpy

src, adir, timing_path, out = sys.argv[sys.argv.index("--") + 1:][:4]
timing = json.load(open(timing_path))
scene = bpy.context.scene
scene.render.fps = timing["fps"]
scene.view_settings.view_transform = "Standard"  # finished frames: pass them through unchanged, no second tone curve
se = scene.sequence_editor_create()
movie = se.strips.new_movie("picture", src, 1, 1)
scene.render.resolution_x, scene.render.resolution_y = movie.elements[0].orig_width, movie.elements[0].orig_height
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 1, movie.frame_final_duration
files = sorted(f for f in os.listdir(adir) if f.startswith("step_"))
for i, (f, s) in enumerate(zip(files, timing["steps"]), 1):
    se.strips.new_sound(f"step{i}", os.path.join(adir, f), 2 + (i % 2), int(round(s["start"] * timing["fps"])) + 1)
im = scene.render.image_settings
im.media_type = "VIDEO"; im.file_format = "FFMPEG"
ff = scene.render.ffmpeg
ff.format = "MPEG4"; ff.codec = "H264"; ff.constant_rate_factor = "HIGH"; ff.audio_codec = "AAC"; ff.audio_bitrate = 192
scene.render.filepath = out
bpy.ops.render.render(animation=True)

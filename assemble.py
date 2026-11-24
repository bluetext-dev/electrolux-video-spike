"""Stage 4: frames and narration into one MP4, with Blender's own encoder (no ffmpeg needed).

    blender -b --factory-startup --python assemble.py -- OUTDIR runs/timing.json out.mp4
"""
import json, os, sys
import bpy

outdir, timing_path, out = sys.argv[sys.argv.index("--") + 1:][:3]
timing = json.load(open(timing_path))
frames = sorted(f for f in os.listdir(os.path.join(outdir, "frames")) if f.endswith(".png"))
scene = bpy.context.scene
scene.render.fps = timing["fps"]
se = scene.sequence_editor_create()
img = se.strips.new_image("frames", os.path.join(outdir, "frames", frames[0]), 1, 1)
for f in frames[1:]:
    img.elements.append(f)
for i, s in enumerate(timing["steps"], 1):
    se.strips.new_sound(f"step{i}", s["audio"], 2, int(round(s["start"] * timing["fps"])) + 1)
first = bpy.data.images.load(os.path.join(outdir, "frames", frames[0]))
scene.render.resolution_x, scene.render.resolution_y = first.size
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 1, len(frames)
im = scene.render.image_settings
im.media_type = "VIDEO"
im.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.ffmpeg.audio_codec = "AAC"
scene.render.ffmpeg.audio_bitrate = 160
scene.render.filepath = out
bpy.ops.render.render(animation=True)

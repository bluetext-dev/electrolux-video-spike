import bpy, sys
s = bpy.context.scene
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 1440, 820, 50
s.render.image_settings.media_type = "IMAGE"; s.render.image_settings.file_format = "PNG"
base = sys.argv[sys.argv.index("--") + 1]
for name, suffix in (("Env_RefCamera", ""), ("Env_RefCamera2", "-2")):
    cam = bpy.data.objects.get(name)
    if cam:
        s.camera = cam
        s.render.filepath = base.replace(".png", suffix + ".png")
        bpy.ops.render.render(write_still=True)

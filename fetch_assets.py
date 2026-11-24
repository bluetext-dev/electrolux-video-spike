"""Download CC0 assets from Poly Haven into assets/: PBR textures, glTF models, one HDRI.

    python3 fetch_assets.py
Writes assets/index.json: for each asset, its kind and the local files the scene script may use.
"""
import json, os, ssl, urllib.request
from llm import HERE

SSL = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
UA = {"User-Agent": "video-pipeline-spike/1.0"}
RES = "2k"
TEXTURES = ["oak_veneer_01", "marble_01", "concrete_floor_02", "white_plaster_02", "denim_fabric"]
MODELS = ["wicker_basket_01", "potted_plant_02", "multi_cleaner_bottle", "bleach_bottle"]
HDRI = "photo_studio_loft_hall"
OUT = os.path.join(HERE, "assets")


def get(url, path=None):
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), context=SSL, timeout=300).read()
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
    return data


index = {}
for t in TEXTURES:
    files = json.loads(get(f"https://api.polyhaven.com/files/{t}"))
    maps = {}
    for key, name in (("Diffuse", "diffuse"), ("nor_gl", "normal"), ("Rough", "roughness"), ("Displacement", "displacement"), ("AO", "ao")):
        if key in files and RES in files[key]:
            fmt = "jpg" if "jpg" in files[key][RES] else "png"
            p = os.path.join(OUT, "textures", t, f"{name}.{fmt}")
            get(files[key][RES][fmt]["url"], p); maps[name] = os.path.relpath(p, HERE)
    index[t] = {"kind": "texture", "maps": maps}
    print("texture", t, list(maps))
for m in MODELS:
    files = json.loads(get(f"https://api.polyhaven.com/files/{m}"))
    g = files["gltf"][RES]["gltf"]
    d = os.path.join(OUT, "models", m)
    p = os.path.join(d, os.path.basename(g["url"])); get(g["url"], p)
    for rel, inc in g.get("include", {}).items():
        get(inc["url"], os.path.join(d, rel))
    info = json.loads(get(f"https://api.polyhaven.com/info/{m}"))
    index[m] = {"kind": "model", "gltf": os.path.relpath(p, HERE), "dimensions_mm": info.get("dimensions")}
    print("model", m, info.get("dimensions"))
files = json.loads(get(f"https://api.polyhaven.com/files/{HDRI}"))
p = os.path.join(OUT, "hdri", f"{HDRI}.hdr"); get(files["hdri"][RES]["hdr"]["url"], p)
index[HDRI] = {"kind": "hdri", "file": os.path.relpath(p, HERE)}
json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1)
print("hdri", HDRI, "\nwrote assets/index.json; licence: CC0 (polyhaven.com)")

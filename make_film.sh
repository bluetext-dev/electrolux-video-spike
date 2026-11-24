#!/bin/sh
# The whole film from what is in this repository, with no model calls and no cloud account:
# the model astra wrote (runs/model/model_v3b.py), the procedure (runs/procedure_v3.json),
# the Kore narration (runs/audio_Kore_v2/), the music (runs/music/bed.mp3) and the logo.
#
#   ./make_film.sh            # full size, about 45 minutes on an M1 Pro laptop
#   ./make_film.sh --preview  # quarter size, every 6th frame, no sound: about 2 minutes
#
# Run it from the repository's root. Needs Blender 5.1 on macOS (afinfo and the system fonts are used).
set -e
cd "$(dirname "$0")"
B="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
MODEL=runs/model/model_v3b.blend
PROC=runs/procedure_v3.json
TIMING=runs/timing_v2.json

"$B" -b --factory-startup --python-exit-code 1 --python runs/model/model_v3b.py -- "$MODEL"

if [ "$1" = "--preview" ]; then
  "$B" -b "$MODEL" --python-exit-code 1 --python video.py -- "$PROC" "$TIMING" runs/preview --preview
  echo "preview frames: runs/preview/frames/"
  exit 0
fi

"$B" -b "$MODEL" --python-exit-code 1 --python video.py -- "$PROC" "$TIMING" runs/final
"$B" -b --factory-startup --python-exit-code 1 --python assemble.py -- runs/final "$TIMING" runs/final/picture.mp4
"$B" -b --factory-startup --python-exit-code 1 --python intro.py -- brand/electrolux-logo.svg "Care guide · Cleaning the drain pump filter · EW7F7649U2" runs/intro
"$B" -b --factory-startup --python-exit-code 1 --python final_mix.py -- runs/intro/frames runs/final/picture.mp4 runs/audio_Kore_v2 runs/music/bed.mp3 "$TIMING" runs/final/film.mp4
echo "film: runs/final/film.mp4"

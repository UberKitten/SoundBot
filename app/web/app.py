import json
import pathlib
import re
from typing import Any, Dict

from fastapi import Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.core.settings import settings
from app.web.models import DB, Sound
from app.web.dependencies import no_cache

app = FastAPI()

templates = Jinja2Templates(directory=settings.web_templates_root)
asset_re = re.compile(".*(/scripts/|/styles/)(.+/)?(.+)-.+(\..+)$")

sound_path = pathlib.Path(settings.sounds_root)

@app.get("/db.json", dependencies=[Depends(no_cache)])
async def db():
    with open("mount/db.json") as db_file:
        db_json: Dict[str, Any] = json.load(db_file)

    db = DB.parse_obj(db_json)

    # Add in sounds that aren't in the existing db
    sound_names = [sound.name for sound in db.sounds]

    for sound_path_file in sound_path.glob('*'):
        if sound_path_file.is_file() and sound_path_file.stem not in sound_names:
            db.sounds.append(Sound(name=sound_path_file.stem))
    
    # Fill in file info for each sound
    for sound in db.sounds:
        sound_files = list(sound_path.glob(f"{sound.name}.*"))
        if len(sound_files) > 0:
            best_match_file = next((file for file in sound_files if file.suffix == ".mp3"), sound_files[0])

            sound.filename = best_match_file.name
            sound.modified = best_match_file.stat().st_mtime_ns

    return db

@app.get("/")
async def index(request: Request):
    static_path = pathlib.Path(settings.web_static_root)

    js_files = list(static_path.joinpath("scripts").glob("**/*.js"))
    css_files = list(static_path.joinpath("styles").glob("**/*.css"))

    js_importmap: Dict[str, Any] = { "imports": {} }

    for js_file in js_files:
        js_matches = asset_re.match(str(js_file.absolute()))
        if js_matches:
            asset_name = js_matches.group(3)
            folder_name = "/scripts/" + (js_matches.group(2) or "")
            file_name = js_file.name

            js_importmap["imports"][asset_name] = folder_name + file_name

    if len(css_files) >= 1:
        css_matches = asset_re.match(str(css_files[0].absolute()))
    else:
        css_matches = None

    if css_matches:
        css_file = css_files[0].name
    else:
        css_file = None

    return templates.TemplateResponse("index.html", {
        "request": request,
        "css_file": css_file,
        "js_importmap": js_importmap
    })

# These must go after routes

app.mount("/sounds", StaticFiles(directory=settings.sounds_root))
app.mount("/", StaticFiles(directory=settings.web_static_root, html=True))

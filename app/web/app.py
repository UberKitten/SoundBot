import json
import pathlib
import re

from typing import Any, Dict

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from starlette.templating import Jinja2Templates

from app.web.models import DB

app = FastAPI()

static_root = "app/web/static"
NO_CACHE_HEADERS = ('cache-control', 'no-store')
templates = Jinja2Templates(directory="app/web/template")
asset_re = re.compile(".*(/scripts/|/styles/)(.+/)?(.+)-.+(\..+)$")

@app.get("/db.json")
async def db(response: Response):
    response.headers[NO_CACHE_HEADERS[0]] = NO_CACHE_HEADERS[1]

    with open("mount/db.json") as db_file:
        db_json: Dict[str, Any] = json.load(db_file)

    db = DB.parse_obj(db_json)
    
    for sound in db.sounds:
        sound_files = list(pathlib.Path("mount/sounds/").glob(f"{sound.name}.*"))
        if len(sound_files) > 0:
            sound_file = sound_files[0]

            for file in sound_files:
                if file.name.endswith(".mp3"):
                    sound_file = file

            sound.filename = sound_file.name
            sound.modified = sound_file.stat().st_mtime_ns

    return db

@app.get("/")
async def index(request: Request):
    static_path = pathlib.Path(static_root)

    js_files = list(static_path.joinpath("scripts").glob("**/*.js"))
    css_files = list(static_path.joinpath("styles").glob("**/*.css"))

    js_importmap:Dict[str, str] = { "imports": {} }

    for js_file in js_files:
        js_matches = asset_re.match(f"{js_file.absolute()}")
        if js_matches:
            asset_name = js_matches.group(3)
            folder_name = "/scripts/" + (js_matches.group(2) or "")
            file_name = js_file.name

            js_importmap["imports"][asset_name] = folder_name + file_name

    if len(css_files) >= 1:
        css_matches = asset_re.match(f"{css_files[0].absolute()}")
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

app.mount("/sounds", StaticFiles(directory="mount/sounds"))
app.mount("/", StaticFiles(directory=static_root, html=True))

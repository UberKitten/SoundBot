import json
import pathlib

from typing import Any, Dict

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from starlette.templating import Jinja2Templates

from app.web.models import DB

app = FastAPI()

NO_CACHE_HEADERS = ('cache-control', 'no-store')

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

templates = Jinja2Templates(directory='app/web/template')

@app.get("/")
async def db(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})

# These must go after routes

app.mount("/sounds", StaticFiles(directory="mount/sounds"))
app.mount("/", StaticFiles(directory="app/web/static", html=True))

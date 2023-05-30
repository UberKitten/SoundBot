import json
import pathlib

from typing import Any, Dict, Union

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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
            sound.filename = sound_files[0].name
            sound.modified = sound_files[0].stat().st_mtime_ns

    return db

# These must go after routes

app.mount("/sounds", StaticFiles(directory="mount/sounds"), name="static")
app.mount("/", StaticFiles(directory="app/web/static", html=True), name="static")

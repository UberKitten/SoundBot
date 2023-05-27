from typing import Union

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

@app.get("/db.json")
async def db():
    return FileResponse("mount/db.json")

# These must go after routes

app.mount("/sounds", StaticFiles(directory="mount/sounds"), name="static")
app.mount("/", StaticFiles(directory="app/web/static", html=True), name="static")


    
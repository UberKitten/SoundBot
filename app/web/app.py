from typing import Union

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()

@app.get("/db.json")
async def read_root():
    return {}

# These must go last
app.mount("/sounds", StaticFiles(directory="app/web/static"), name="static")
app.mount("/", StaticFiles(directory="app/web/static", html=True), name="static")


    
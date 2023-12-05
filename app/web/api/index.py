import logging
import pathlib
import re
from typing import Any, Dict

from fastapi import APIRouter, Request
from starlette.templating import Jinja2Templates

from app.core.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory=settings.templates_folder)
asset_re = re.compile(r".*(/scripts/|/styles/)(.+/)?(.+)-.+(\..+)$")


@router.get("/")
async def index(request: Request):
    static_path = pathlib.Path(settings.static_ui_folder)

    js_files = list(static_path.joinpath("scripts").glob("**/*.js"))
    css_files = list(static_path.joinpath("styles").glob("**/*.css"))

    js_importmap: Dict[str, Any] = {"imports": {}}

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

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "css_file": css_file, "js_importmap": js_importmap},
    )

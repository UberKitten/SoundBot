import logging
import pathlib
import re
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse
from starlette.templating import Jinja2Templates

from soundbot.core.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory=settings.templates_folder)
asset_re = re.compile(r".*[/\\](scripts|styles)[/\\](.+[/\\])?(.+)-.+(\..+)$")


@router.get("/")
async def index(request: Request):
    """
    Uses Jinja2 templates to serve index.html with JS and CSS resources.
    """
    static_path = pathlib.Path(settings.static_folder)

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
        else:
            logger.warning(f"JS file didn't match pattern: {js_file}")

    logger.debug(f"Generated import map: {js_importmap}")

    if len(css_files) >= 1:
        css_matches = asset_re.match(str(css_files[0].absolute()))
    else:
        css_matches = None

    if css_matches:
        css_file = css_files[0].name
    else:
        css_file = None

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "css_file": css_file,
            "js_importmap": js_importmap,
            "app_title": settings.app_title,
        },
    )


@router.get("/site.webmanifest")
async def webmanifest():
    """Dynamic PWA manifest that reflects the configured app title."""
    short_name = settings.app_short_title or settings.app_title
    return ORJSONResponse(
        {
            "name": settings.app_title,
            "short_name": short_name,
            "start_url": "./",
            "icons": [
                {
                    "src": "/android-chrome-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": "/android-chrome-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
            "theme_color": "#ffffff",
            "background_color": "#ffffff",
            "display": "fullscreen",
        },
        media_type="application/manifest+json",
    )

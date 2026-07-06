import logging
import pathlib
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse
from starlette.templating import Jinja2Templates

from soundbot.core.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory=settings.templates_folder)
asset_re = re.compile(r".*[/\\](scripts|styles)[/\\](.+[/\\])?(.+)-.+(\..+)$")

# Checked-in, un-hashed third-party ESM bundles served from /vendor/
# (gulp copyStatic copies web/static/vendor/** -> web/dist/vendor/**).
# Each is a fully self-contained bundle with no import statements, so the two
# entries resolve independently (the regions plugin bundles its own copy of the
# core base classes and does not import "wavesurfer"). See
# web/static/vendor/README.md for provenance.
VENDOR_IMPORTS: Dict[str, str] = {
    "wavesurfer": "/vendor/wavesurfer.esm.js",
    "wavesurfer-regions": "/vendor/regions.esm.js",
}


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

    # Merge in the vendored bare-specifier -> URL mappings. Warn (don't fail) if
    # a vendored file is missing from the build so the page still loads.
    for specifier, url in VENDOR_IMPORTS.items():
        vendor_file = static_path.joinpath(url.lstrip("/"))
        if not vendor_file.exists():
            logger.warning(f"Vendored asset missing for '{specifier}': {vendor_file}")
        js_importmap["imports"][specifier] = url

    logger.debug(f"Generated import map: {js_importmap}")

    # Collect every hashed stylesheet (base soundboard.css + admin.css, etc.).
    # Sorted for deterministic ordering; the stylesheets are additive and do not
    # override one another, so cascade order among them is not significant.
    css_file_names: List[str] = []
    for css_file in sorted(css_files, key=lambda p: p.name):
        css_matches = asset_re.match(str(css_file.absolute()))
        if css_matches:
            css_file_names.append(css_file.name)
        else:
            logger.warning(f"CSS file didn't match pattern: {css_file}")

    # Back-compat single value: first stylesheet (or None) for older templates.
    css_file = css_file_names[0] if css_file_names else None

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "css_file": css_file,
            "css_files": css_file_names,
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

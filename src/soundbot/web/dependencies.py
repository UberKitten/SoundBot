
from fastapi import HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from soundbot.core.settings import settings

_bearer = HTTPBearer()


async def no_cache(response: Response):
    response.headers['cache-control'] = 'no-store'


async def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API key not configured")
    if credentials.credentials != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

from fastapi import Response

async def no_cache(response: Response):
    response.headers['cache-control'] = 'no-store'
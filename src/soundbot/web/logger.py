from typing import Any, override

import hypercorn.logging


class HypercornLogger(hypercorn.logging.Logger):
    @override
    async def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        await super().debug(message, *args, **kwargs)

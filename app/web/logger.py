from typing import Any, Coroutine

import hypercorn.logging


class HypercornLogger(hypercorn.logging.Logger):
    def info(self, message: str, *args: Any, **kwargs: Any) -> Coroutine[Any, Any, None]:
        return super().debug(message, *args, **kwargs)

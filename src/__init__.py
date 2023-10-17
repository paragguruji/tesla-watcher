from types import TracebackType
from typing import Callable, List, Tuple, Optional, Type

from src.incentives import federal_us, state_nj, state_ny
from src.teslawatcher import TeslaWatcher

WSGI_START_RESPONSE_TYPEDEF = Callable[
    [str,
     List[Tuple[str, str]],
     Optional[tuple[Type[BaseException], BaseException, TracebackType] | tuple[None, None, None]]],
    Callable[[bytes], None]
]

import logging
from functools import lru_cache
import sys

from rich.console import Console
from rich.logging import RichHandler

console = Console(color_system="256", width=200, style="green")


@lru_cache(maxsize=None)
def get_logger(module):
    if "pytest" not in sys.modules:
        logger = logging.getLogger(module)
        logger.setLevel(logging.INFO)
    else:
        logger = logging.getLogger()

    logger.propagate = True
    if not logger.handlers:
        rich_handler = RichHandler(console=console)
        logger.addHandler(rich_handler)
        stream_handler = logging.StreamHandler()
        logger.addHandler(stream_handler)
    return logger


# LRU cache helps make repeated function calls faster by memoizing them
# @lru_cache()
# def get_logger(module_name):
#     logger = logging.getLogger(module_name)
#     handler = RichHandler(
#         rich_tracebacks=True, console=console, tracebacks_show_locals=True
#     )
#     handler.setFormatter(
#         logging.Formatter("[ %(threadName)s:%(funcName)s:%(lineno)d ] - %(message)s")
#     )
#     logger.addHandler(handler)
#     logger.setLevel(logging.DEBUG)
#     return logger

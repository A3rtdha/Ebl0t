"""
Повтор запросов при временных сетевых ошибках (обрыв соединения, таймаут).
Используй для defer() и других вызовов Discord API.
"""
import asyncio
import logging

log = logging.getLogger(__name__)

# Исключения, при которых имеет смысл повторить запрос
NETWORK_ERRORS = (
    "ClientConnectorError",
    "ClientError",
    "ServerDisconnectedError",
    "ClientOSError",
    "ConnectionError",
    "OSError",
)


def _is_network_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in NETWORK_ERRORS:
        return True
    mod = type(exc).__module__
    if "aiohttp" in mod and "Client" in name:
        return True
    return False


async def retry_on_network(async_fn, max_attempts: int = 3, delay: float = 1.5):
    """
    Выполняет async_fn(); при сетевой ошибке повторяет до max_attempts раз с паузой delay.
    async_fn — корутина без аргументов, например: lambda: inter.response.defer()
    """
    last = None
    for attempt in range(max_attempts):
        try:
            return await async_fn()
        except Exception as e:
            last = e
            if _is_network_error(e) and attempt < max_attempts - 1:
                log.warning("Сетевая ошибка %s, повтор через %.1f с (попытка %d/%d)", e, delay, attempt + 1, max_attempts)
                await asyncio.sleep(delay)
            else:
                raise
    if last is not None:
        raise last

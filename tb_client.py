import aiohttp, asyncio
from settings import settings

TB_TELEM_PATH = "/api/v1/{token}/telemetry"
TB_ATTR_PATH  = "/api/v1/{token}/attributes"

async def _post_tb(url: str, payload: dict):
    delay = settings.TB_RETRY_BACKOFF_BASE_MS / 1000.0
    for attempt in range(settings.TB_RETRY_MAX):
        try:
            timeout = aiohttp.ClientTimeout(total=settings.TB_TIMEOUT_S)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(url, json=payload) as r:
                    text = await r.text()
                    if 200 <= r.status < 300:
                        return text
                    if 500 <= r.status < 600:
                        raise RuntimeError(f"TB 5xx {r.status}")
                    raise RuntimeError(f"TB 4xx {r.status}: {text}")
        except Exception:
            if attempt == settings.TB_RETRY_MAX - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2

async def post_telemetry(token: str, telemetry: dict):
    url = f"{settings.TB_HOST}{TB_TELEM_PATH.format(token=token)}"
    return await _post_tb(url, telemetry)

async def post_attributes(token: str, attrs: dict):
    url = f"{settings.TB_HOST}{TB_ATTR_PATH.format(token=token)}"
    return await _post_tb(url, attrs)

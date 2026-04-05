"""Async Polymarket CLOB API client."""
import aiohttp


async def fetch_market_details(market_id: str) -> dict:
    """Fetch market details from Polymarket CLOB API.

    Args:
        market_id: The market condition ID.

    Returns:
        Market metadata dict from the API.

    Raises:
        Exception: On non-200 response.
    """
    url = f"https://clob.polymarket.com/markets/{market_id}"
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"API error: {resp.status}")
            return await resp.json()

"""Exchange rates: units of each currency per 1 ILS (ECB data via Frankfurter, free, no key)."""
import httpx

FX_URL = "https://api.frankfurter.dev/v1/latest"
CURRENCIES = ("INR", "MYR", "USD", "EUR")


async def fetch_rates(client: httpx.AsyncClient) -> dict[str, float]:
    resp = await client.get(FX_URL, params={"base": "ILS", "symbols": ",".join(CURRENCIES)})
    resp.raise_for_status()
    rates = resp.json()["rates"]
    rates["ILS"] = 1.0
    return rates

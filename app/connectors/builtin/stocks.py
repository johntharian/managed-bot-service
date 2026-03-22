import httpx
from datetime import datetime, timezone, timedelta
from app.connectors.base import BaseConnector, ContextBlock, ToolDefinition, ToolResult
from app.connectors.credentials import CredentialManager


class StocksConnector(BaseConnector):
    name = "stocks"
    display_name = "Stocks"
    token_budget = 60

    API_BASE = "https://finnhub.io/api/v1"

    def __init__(self, cred_manager: "CredentialManager") -> None:
        super().__init__(cred_manager)

    async def connect(self, user_id: str, creds: dict, db) -> None:
        await self.cred_manager.store(user_id, self.name, creds, db)

    async def disconnect(self, user_id: str, db) -> None:
        await self.cred_manager.deactivate(user_id, self.name, db)

    async def get_context(self, user_id: str, db) -> ContextBlock:
        creds = await self.cred_manager.get(user_id, self.name, db)
        if not creds:
            return ContextBlock(content="**Stocks:** Not configured.")

        api_key = creds.get("api_key", "")
        watchlist = creds.get("watchlist", [])[:5]

        if not watchlist:
            return ContextBlock(content="**Stocks:** No watchlist configured.")

        parts = []
        async with httpx.AsyncClient() as client:
            for symbol in watchlist:
                try:
                    resp = await client.get(
                        f"{self.API_BASE}/quote",
                        params={"symbol": symbol, "token": api_key},
                    )
                    if resp.status_code == 429:
                        return ContextBlock(content="**Stocks:** Rate limit reached. Try again shortly.")
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("c") == 0 and data.get("t") == 0:
                        continue
                    parts.append(f"{symbol} ${data['c']:.2f} ({data['dp']:+.2f}%)")
                except (httpx.HTTPError, KeyError, ValueError):
                    continue

        if not parts:
            return ContextBlock(content="**Stocks:** No data available.")

        return ContextBlock(content="**Stocks:** " + ", ".join(parts))

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="stocks_get_quote",
                description="Get the current quote for a stock symbol, including price, change percentage, high, and low.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Stock ticker symbol, e.g. AAPL",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            ToolDefinition(
                name="stocks_get_portfolio",
                description="Get quotes for multiple stock symbols at once.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of stock ticker symbols, e.g. [\"AAPL\", \"GOOGL\"]",
                        },
                    },
                    "required": ["symbols"],
                },
            ),
            ToolDefinition(
                name="stocks_set_watchlist",
                description="Update the user's stock watchlist.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of stock ticker symbols to watch.",
                        },
                    },
                    "required": ["symbols"],
                },
            ),
            ToolDefinition(
                name="stocks_get_news",
                description="Get recent company news for a stock symbol.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Stock ticker symbol, e.g. AAPL",
                        },
                        "from_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format. Defaults to 7 days ago.",
                        },
                        "to_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format. Defaults to today.",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict, user_id: str, db) -> ToolResult:
        creds = await self.cred_manager.get(user_id, self.name, db)
        if not creds:
            return ToolResult(content=None, error="Stocks connector is not configured.")

        api_key = creds.get("api_key", "")

        if tool_name == "stocks_get_quote":
            symbol = args.get("symbol", "").upper()
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self.API_BASE}/quote",
                        params={"symbol": symbol, "token": api_key},
                    )
                    if resp.status_code == 429:
                        return ToolResult(content=None, error="Rate limit reached. Try again shortly.")
                    resp.raise_for_status()
                    data = resp.json()
                if data.get("c") == 0 and data.get("t") == 0:
                    return ToolResult(content=None, error=f"Invalid or unknown symbol: {symbol}")
                return ToolResult(content={
                    "symbol": symbol,
                    "price": data.get("c"),
                    "change_percent": data.get("dp"),
                    "high": data.get("h"),
                    "low": data.get("l"),
                })
            except Exception as e:
                return ToolResult(content=None, error=str(e))

        elif tool_name == "stocks_get_portfolio":
            symbols = [s.upper() for s in args.get("symbols", [])][:20]
            results = []
            async with httpx.AsyncClient() as client:
                for symbol in symbols:
                    try:
                        resp = await client.get(
                            f"{self.API_BASE}/quote",
                            params={"symbol": symbol, "token": api_key},
                        )
                        if resp.status_code == 429:
                            return ToolResult(content=None, error="Rate limit reached. Try again shortly.")
                        resp.raise_for_status()
                        data = resp.json()
                        if data.get("c") == 0 and data.get("t") == 0:
                            continue
                        results.append({
                            "symbol": symbol,
                            "price": data.get("c"),
                            "change_percent": data.get("dp"),
                            "high": data.get("h"),
                            "low": data.get("l"),
                        })
                    except (httpx.HTTPError, KeyError, ValueError):
                        continue
            return ToolResult(content=results)

        elif tool_name == "stocks_set_watchlist":
            symbols = [s.upper() for s in args.get("symbols", [])]
            creds["watchlist"] = symbols
            await self.cred_manager.store(user_id, self.name, creds, db)
            return ToolResult(content={"watchlist": symbols, "updated": True})

        elif tool_name == "stocks_get_news":
            symbol = args.get("symbol", "").upper()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            from_date = args.get("from_date") or week_ago
            to_date = args.get("to_date") or today
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self.API_BASE}/company-news",
                        params={"symbol": symbol, "from": from_date, "to": to_date, "token": api_key},
                    )
                    if resp.status_code == 429:
                        return ToolResult(content=None, error="Rate limit reached. Try again shortly.")
                    resp.raise_for_status()
                    articles = resp.json()
                return ToolResult(content=articles)
            except Exception as e:
                return ToolResult(content=None, error=str(e))

        return ToolResult(content=None, error=f"Unknown tool: {tool_name}")

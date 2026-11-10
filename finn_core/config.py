"""Portfolio names and exchange-symbol aliases. One place to edit them."""

PORTFOLIO = (
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ITC",
    "SUNPHARMA",
    "MARUTI",
    "LT",
    "BAJFINANCE",
    "TITAN",
    "CGPOWER",
    "BHARATFORG",
    "MARICO",
    "PERSISTENT",
    "TRENT",
    "POLYCAB",
    "DIXON",
    "BHARATSEATS",
)

# Brief name -> NSE and Yahoo symbol. Bharat Seats is BHARATSE on both.
MARKET_SYMBOL = {
    "BHARATSEATS": "BHARATSE",
}


def market_symbol(symbol: str) -> str:
    key = symbol.upper()
    return MARKET_SYMBOL.get(key, key)

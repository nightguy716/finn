"""FINN data layer. NSE filings, keyword classification, EOD alerts."""

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

# AGENTS.md writes Bharat Seats as BHARATSEATS. NSE and Yahoo Finance use BHARATSE.
MARKET_SYMBOL = {"BHARATSEATS": "BHARATSE"}


def market_symbol(symbol: str) -> str:
    return MARKET_SYMBOL.get(symbol, symbol)

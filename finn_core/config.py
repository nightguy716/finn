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


COMPANY_NAMES = {
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "HDFCBANK": "HDFC Bank",
    "INFY": "Infosys",
    "ITC": "ITC",
    "SUNPHARMA": "Sun Pharmaceutical",
    "MARUTI": "Maruti Suzuki",
    "LT": "Larsen & Toubro",
    "BAJFINANCE": "Bajaj Finance",
    "TITAN": "Titan Company",
    "CGPOWER": "CG Power and Industrial Solutions",
    "BHARATFORG": "Bharat Forge",
    "MARICO": "Marico",
    "PERSISTENT": "Persistent Systems",
    "TRENT": "Trent",
    "POLYCAB": "Polycab India",
    "DIXON": "Dixon Technologies",
    "BHARATSEATS": "Bharat Seats",
}


def market_symbol(symbol: str) -> str:
    key = symbol.upper()
    return MARKET_SYMBOL.get(key, key)


def company_name(symbol: str) -> str:
    key = symbol.upper()
    return COMPANY_NAMES.get(key, key)

"""The normalized taker row every source produces: one row per fill, aggressor side only.

  {venue, market, t_ms, side, qty, price, usd, taker}

side +1 = taker bought YES (or sold NO; long on a perp); -1 = taker bought NO (short on a perp).
price is the YES price (perp: trade price). usd is the taker's cash at risk on a binary,
qty*price for +1 and qty*(1-price) for -1; on a perp it is notional, qty*price.
"""


def binary_row(venue: str, market: str, t_ms: int, side: int, qty: float, yes_price: float, taker: str = "") -> dict:
    return {"venue": venue, "market": market, "t_ms": t_ms, "side": side, "qty": qty, "price": yes_price,
            "usd": qty * (yes_price if side > 0 else 1 - yes_price), "taker": taker}


def perp_row(venue: str, market: str, t_ms: int, side: int, qty: float, price: float, taker: str = "") -> dict:
    return {"venue": venue, "market": market, "t_ms": t_ms, "side": side, "qty": qty, "price": price, "usd": qty * price, "taker": taker}

from typing import Optional

import pandas as pd
import yfinance as yf

from config import MARKETS

from models import MarketContext


def _clean_series(
    df,
    column,
):

    series = df[column]

    if isinstance(
        series,
        pd.DataFrame,
    ):
        series = series.iloc[:, 0]

    return series.dropna()


def get_market_context(
    asset: str,
) -> MarketContext:

    cfg = MARKETS[asset]

    symbol = cfg["symbol"]

    try:

        df = yf.download(
            symbol,
            period="5d",
            interval="15m",
            progress=False,
            auto_adjust=False,
            threads=False,
        )

        if df is None or df.empty:
            raise RuntimeError(
                "No market data returned"
            )

        close = _clean_series(
            df,
            "Close",
        )

        if len(close) < 200:
            raise RuntimeError(
                f"Not enough 15m bars: {len(close)}"
            )

        ema50 = (
            close
            .ewm(
                span=50,
                adjust=False,
            )
            .mean()
        )

        ema200 = (
            close
            .ewm(
                span=200,
                adjust=False,
            )
            .mean()
        )

        price = float(
            close.iloc[-1]
        )

        e50 = float(
            ema50.iloc[-1]
        )

        e200 = float(
            ema200.iloc[-1]
        )

        if price > e50 > e200:

            trend = "Bullish"

        elif price < e50 < e200:

            trend = "Bearish"

        else:

            trend = "Mixed"

        change_pct: Optional[
            float
        ] = None

        if len(close) >= 2:

            change_pct = float(
                (
                    close.iloc[-1]
                    / close.iloc[-2]
                    - 1
                )
                * 100
            )

        atr_pct = None

        try:

            high = _clean_series(
                df,
                "High",
            )

            low = _clean_series(
                df,
                "Low",
            )

            previous_close = (
                close.shift(1)
            )

            tr = pd.concat(
                [
                    high - low,
                    (
                        high
                        - previous_close
                    ).abs(),
                    (
                        low
                        - previous_close
                    ).abs(),
                ],
                axis=1,
            ).max(axis=1)

            atr = (
                tr
                .rolling(14)
                .mean()
                .iloc[-1]
            )

            if price:

                atr_pct = float(
                    atr
                    / price
                    * 100
                )

        except Exception:

            atr_pct = None

        return MarketContext(
            asset=asset,
            symbol=symbol,
            price=price,
            ema50=e50,
            ema200=e200,
            trend=trend,
            change_pct=change_pct,
            atr_pct=atr_pct,
        )

    except Exception as exc:

        print(
            f"Market data error "
            f"{asset}: {exc}"
        )

        return MarketContext(
            asset=asset,
            symbol=symbol,
            price=None,
            ema50=None,
            ema200=None,
            trend="Unavailable",
        )


def get_context_for_assets(
    assets: list[str],
):

    return [
        get_market_context(asset)
        for asset in assets
        if asset in MARKETS
    ]
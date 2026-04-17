# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"
ALLOWED_CHAT_ID = -1003130189488

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]


# ================= BINANCE FUTURES =================
def get_binance_futures(symbol, interval="15m"):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}USDT&interval={interval}&limit=150"
        res = requests.get(url, timeout=10).json()

        if isinstance(res, dict):
            return None

        df = pd.DataFrame(res)[[0,1,2,3,4,5]]
        df.columns = ["time","open","high","low","close","volume"]
        df = df.astype(float)

        df["time"] = pd.to_datetime(df["time"], unit='ms')
        df.set_index("time", inplace=True)

        return df
    except:
        return None


# ================= BYBIT FUTURES =================
def get_bybit_futures(symbol, interval="15"):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}USDT&interval={interval}&limit=150"
        res = requests.get(url, timeout=10).json()

        if res.get("retCode") != 0:
            return None

        data = res["result"]["list"]

        df = pd.DataFrame(data)
        df = df.iloc[::-1]

        df.columns = ["time","open","high","low","close","volume","turnover"]
        df = df[["time","open","high","low","close","volume"]]

        df = df.astype(float)
        df["time"] = pd.to_datetime(df["time"], unit='ms')
        df.set_index("time", inplace=True)

        return df
    except:
        return None


# ================= UNIVERSAL =================
def get_market_data(symbol, interval="15m"):
    df = get_binance_futures(symbol, interval)
    if df is not None:
        return df, "Binance"

    df = get_bybit_futures(symbol)
    if df is not None:
        return df, "Bybit"

    return None, None


# ================= INDICATORS =================
def add_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
    df["vol_ma"] = df["volume"].rolling(20).mean()
    return df


def get_trend(df):
    last = df.iloc[-1]
    return "LONG" if last["ema20"] > last["ema50"] else "SHORT"


# ================= FLAT FILTER =================
def is_flat(df):
    atr = df["atr"].iloc[-1]
    avg_range = (df["high"] - df["low"]).rolling(20).mean().iloc[-1]
    return atr < avg_range * 0.7


# ================= VOLUME =================
def volume_spike(df):
    last = df.iloc[-1]
    return last["volume"] > last["vol_ma"] * 1.5


# ================= ZONE =================
def get_zone(df, trend):
    candles = df.tail(12)

    for i in range(len(candles)-1, -1, -1):
        c = candles.iloc[i]

        if trend == "LONG" and c["close"] < c["open"]:
            return c["low"], c["open"]

        if trend == "SHORT" and c["close"] > c["open"]:
            return c["open"], c["high"]

    return None


# ================= SMART ENTRY =================
def confirm_entry(df, zone, trend):
    if not zone:
        return None

    low, high = zone

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    # LONG
    if trend == "LONG":
        sweep = prev2["low"] < low
        reclaim = prev["close"] > low
        confirm = last["close"] > prev["high"]

        if sweep and reclaim and confirm:
            return last["close"]

    # SHORT
    if trend == "SHORT":
        sweep = prev2["high"] > high
        reclaim = prev["close"] < high
        confirm = last["close"] < prev["low"]

        if sweep and reclaim and confirm:
            return last["close"]

    return None


# ================= TRADE =================
def build_trade(df, trend, zone):
    if not zone:
        return None

    if is_flat(df):
        return None

    if not volume_spike(df):
        return None

    entry = confirm_entry(df, zone, trend)

    if not entry:
        return None

    low, high = zone
    atr = df["atr"].iloc[-1]

    if trend == "LONG":
        stop = low - atr * 1.2
        risk = entry - stop

        tp1 = entry + risk * 1
        tp2 = entry + risk * 2
        tp3 = entry + risk * 4

    else:
        stop = high + atr * 1.2
        risk = stop - entry

        tp1 = entry - risk * 1
        tp2 = entry - risk * 2
        tp3 = entry - risk * 4

    return entry, stop, tp1, tp2, tp3


# ================= ANALYSIS =================
def analyze(df, df_h):
    df = add_indicators(df)
    df_h = add_indicators(df_h)

    trend = get_trend(df)
    higher = get_trend(df_h)

    high_liq = df["high"].rolling(30).max().iloc[-1]
    low_liq = df["low"].rolling(30).min().iloc[-1]

    state = "⚖️ ФЛЭТ"
    scenario = "Не входить"

    if trend == higher:
        if trend == "LONG":
            state = "📈 ЛОНГ"
            scenario = "Ищем вход в лонг"
        else:
            state = "📉 ШОРТ"
            scenario = "Ищем вход в шорт"

    zone = get_zone(df, trend)

    return state, scenario, high_liq, low_liq, zone, trend, df


# ================= USER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    text = update.message.text.strip().upper()

    if not text.startswith("/"):
        return

    symbol = text.replace("/", "").replace("USDT", "").strip()

    df, source = get_market_data(symbol, "15m")
    df_h, _ = get_market_data(symbol, "1h")

    if df is None or df_h is None:
        await update.message.reply_text("❌ Монета не найдена")
        return

    state, scenario, high_liq, low_liq, zone, trend, df = analyze(df, df_h)

    msg = f"{symbol}/USDT ({source})\n\n{state}\n\n"
    msg += f"💧 Ликвидность:\n↑ {round(high_liq,4)}\n↓ {round(low_liq,4)}\n\n"
    msg += f"📌 Сценарий:\n{scenario}\n\n"

    if zone:
        msg += f"📍 Зона: {round(zone[0],4)} - {round(zone[1],4)}\n\n"

    trade = build_trade(df, trend, zone)

    if trade:
        entry, stop, tp1, tp2, tp3 = trade

        msg += f"""🚀 СИГНАЛ

{"📈 ЛОНГ" if trend=="LONG" else "📉 ШОРТ"}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}
"""
    else:
        msg += "⏳ Нет входа (ждём подтверждение)"

    msg += "\n\n⚠️ Оценивайте свои финансовые возможности и риски"

    await update.message.reply_text(msg)


# ================= AUTO =================
async def scan_market(app):
    await asyncio.sleep(10)

    while True:
        for symbol in SYMBOLS:
            df, source = get_market_data(symbol, "15m")
            df_h, _ = get_market_data(symbol, "1h")

            if df is None or df_h is None:
                continue

            df = add_indicators(df)
            df_h = add_indicators(df_h)

            trend = get_trend(df)
            if trend != get_trend(df_h):
                continue

            zone = get_zone(df, trend)
            trade = build_trade(df, trend, zone)

            if not trade:
                continue

            entry, stop, tp1, tp2, tp3 = trade

            text = f"""🚨 СИГНАЛ {symbol} ({source})

{"📈 ЛОНГ" if trend=="LONG" else "📉 ШОРТ"}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}
"""

            await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text)

        await asyncio.sleep(600)


# ================= START =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))


async def on_start(app):
    asyncio.create_task(scan_market(app))


app.post_init = on_start

app.run_polling()

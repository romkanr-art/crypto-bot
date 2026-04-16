# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"
ALLOWED_CHAT_ID = -1003130189488

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]


# === DATA ===
def get_klines(symbol, interval="15m"):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit=100"
    res = requests.get(url).json()

    if isinstance(res, dict):
        return None

    df = pd.DataFrame(res)[[0,1,2,3,4,5]]
    df.columns = ["time","open","high","low","close","volume"]
    df = df.astype(float)

    df["time"] = pd.to_datetime(df["time"], unit='ms')
    df.set_index("time", inplace=True)

    return df


# === TREND ===
def get_trend(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    last = df.iloc[-1]
    return "LONG" if last["ema20"] > last["ema50"] else "SHORT"


# === STRUCTURE ===
def get_market_structure(df):
    highs = df["high"].rolling(5).max()
    lows = df["low"].rolling(5).min()

    if highs.iloc[-1] > highs.iloc[-5] and lows.iloc[-1] > lows.iloc[-5]:
        return "UPTREND"

    if highs.iloc[-1] < highs.iloc[-5] and lows.iloc[-1] < lows.iloc[-5]:
        return "DOWNTREND"

    return "RANGE"


# === ORDER BLOCK ===
def get_order_block(df, trend):
    candles = df.tail(10)

    for i in range(len(candles)-1, -1, -1):
        c = candles.iloc[i]

        if trend == "LONG" and c["close"] < c["open"]:
            return c["low"], c["open"]

        if trend == "SHORT" and c["close"] > c["open"]:
            return c["open"], c["high"]

    return None


# === SMART ANALYSIS ===
def analyze_market_state(df, df_h):
    trend = get_trend(df)
    higher_trend = get_trend(df_h)
    structure = get_market_structure(df)

    liquidity_high = df["high"].rolling(20).max().iloc[-1]
    liquidity_low = df["low"].rolling(20).min().iloc[-1]

    if trend != higher_trend:
        return "RANGE", f"""
Против старшего тренда

Сценарий:
Движение по {higher_trend}

Действие:
Лучше не входить
"""

    if structure == "UPTREND":
        return "LONG", f"""
Восходящая структура

Ликвидность:
Сверху: {round(liquidity_high,4)}
Снизу: {round(liquidity_low,4)}

Сценарий:
Рост после отката

Действие:
Ждать откат
"""

    if structure == "DOWNTREND":
        return "SHORT", f"""
Нисходящая структура

Ликвидность:
Сверху: {round(liquidity_high,4)}
Снизу: {round(liquidity_low,4)}

Сценарий:
Падение после отката

Действие:
Ждать откат
"""

    return "RANGE", f"""
Флэт

Ликвидность:
Сверху: {round(liquidity_high,4)}
Снизу: {round(liquidity_low,4)}

Действие:
Не входить
"""


# === SIGNAL FILTER ===
def analyze(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    df["tr"] = df["high"] - df["low"]
    df["atr"] = df["tr"].rolling(14).mean()

    df["+dm"] = df["high"].diff().clip(lower=0)
    df["-dm"] = -df["low"].diff().clip(upper=0)

    df["+di"] = 100 * (df["+dm"].rolling(14).mean() / df["atr"])
    df["-di"] = 100 * (df["-dm"].rolling(14).mean() / df["atr"])

    df["dx"] = (abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"])) * 100
    df["adx"] = df["dx"].rolling(14).mean()

    df["vol_ma"] = df["volume"].rolling(20).mean()

    last = df.iloc[-1]

    if last["adx"] < 20:
        return None

    trend = "LONG" if last["ema20"] > last["ema50"] else "SHORT"

    if trend == "LONG" and last["close"] <= last["open"]:
        return None

    if trend == "SHORT" and last["close"] >= last["open"]:
        return None

    if last["volume"] < last["vol_ma"] * 1.3:
        return None

    strength = "СИЛЬНЫЙ" if last["adx"] > 25 else "СРЕДНИЙ"

    return trend, strength


# === TRADE ===
def build_trade(df, trend):
    ob = get_order_block(df, trend)
    if not ob:
        return None

    ob_low, ob_high = ob
    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

    if trend == "LONG":
        entry = ob_low + (ob_high - ob_low) * 0.25
        stop = ob_low - atr * 0.5
        tp1 = entry + atr * 2
        tp2 = entry + atr * 3
        tp3 = entry + atr * 4
    else:
        entry = ob_high - (ob_high - ob_low) * 0.25
        stop = ob_high + atr * 0.5
        tp1 = entry - atr * 2
        tp2 = entry - atr * 3
        tp3 = entry - atr * 4

    return entry, stop, tp1, tp2, tp3


# === FORMAT ===
def format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3):
    side = "ЛОНГ" if trend == "LONG" else "ШОРТ"

    return f"""
Сигнал: {side}
Сила: {strength}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}
"""


# === HANDLE ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    symbol = update.message.text.upper()

    df = get_klines(symbol)
    df_h = get_klines(symbol, "1h")

    if df is None or df_h is None:
        await update.message.reply_text("Монета не найдена")
        return

    trend_state, comment = analyze_market_state(df, df_h)

    trend_text = {
        "LONG": "ЛОНГ",
        "SHORT": "ШОРТ",
        "RANGE": "ФЛЭТ"
    }.get(trend_state, "ФЛЭТ")

    text = f"""
{symbol}/USDT

Рынок: {trend_text}

{comment}
"""

    result = analyze(df)

    if result:
        trend, strength = result

        if trend == get_trend(df_h):
            trade = build_trade(df, trend)

            if trade:
                entry, stop, tp1, tp2, tp3 = trade
                text += "\n\n" + format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3)

    await update.message.reply_text(text)


# === AUTO ===
async def scan_market(app):
    while True:
        for symbol in SYMBOLS:
            df = get_klines(symbol)
            df_h = get_klines(symbol, "1h")

            if df is None or df_h is None:
                continue

            price = df["close"].iloc[-1]
            df["ema20"] = df["close"].ewm(span=20).mean()
            ema = df["ema20"].iloc[-1]

            atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

            if abs(price - ema) < atr * 0.5:
                await app.bot.send_message(
                    chat_id=ALLOWED_CHAT_ID,
                    text=f"{symbol} подходит к зоне входа"
                )

            result = analyze(df)
            if not result:
                continue

            trend, strength = result

            if trend != get_trend(df_h):
                continue

            trade = build_trade(df, trend)
            if not trade:
                continue

            entry, stop, tp1, tp2, tp3 = trade

            text = f"СИГНАЛ {symbol}\n" + format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3)

            await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text)

        await asyncio.sleep(900)


# === START ===
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))


async def on_start(app):
    asyncio.create_task(scan_market(app))


app.post_init = on_start

app.run_polling()

# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"
ALLOWED_CHAT_ID = -1003130189488  # ВСТАВЬ СЮДА ID ГРУППЫ

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


# === ANALYZE ===
def analyze(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # ADX
    df["tr"] = df["high"] - df["low"]
    df["atr"] = df["tr"].rolling(14).mean()

    df["+dm"] = df["high"].diff().clip(lower=0)
    df["-dm"] = -df["low"].diff().clip(upper=0)

    df["+di"] = 100 * (df["+dm"].rolling(14).mean() / df["atr"])
    df["-di"] = 100 * (df["-dm"].rolling(14).mean() / df["atr"])

    df["dx"] = (abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"])) * 100
    df["adx"] = df["dx"].rolling(14).mean()

    # Volume
    df["vol_ma"] = df["volume"].rolling(20).mean()

    last = df.iloc[-1]

    # ❌ флэт
    if last["adx"] < 20:
        return None

    trend = "LONG" if last["ema20"] > last["ema50"] else "SHORT"

    # откат
    if trend == "LONG" and last["low"] > last["ema20"]:
        return None
    if trend == "SHORT" and last["high"] < last["ema20"]:
        return None

    # свеча
    if trend == "LONG" and last["close"] <= last["open"]:
        return None
    if trend == "SHORT" and last["close"] >= last["open"]:
        return None

    # объем
    if last["volume"] < last["vol_ma"] * 1.5:
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


# === MESSAGE ===
def format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3):
    side = "ЛОНГ" if trend == "LONG" else "ШОРТ"

    return f"""
{symbol}/USDT

Сигнал: {side}
Сила: {strength}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}

Риск: 1%
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

    trend_h = get_trend(df_h)

    result = analyze(df)
    if result is None:
        await update.message.reply_text("Нет сигнала")
        return

    trend, strength = result

    if trend != trend_h:
        await update.message.reply_text("Против старшего тренда")
        return

    trade = build_trade(df, trend)
    if not trade:
        await update.message.reply_text("Нет точки входа")
        return

    entry, stop, tp1, tp2, tp3 = trade

    text = format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3)

    await update.message.reply_text(text)


# === AUTO SIGNALS ===
async def scan_market(app):
    while True:
        for symbol in SYMBOLS:
            df = get_klines(symbol)
            df_h = get_klines(symbol, "1h")

            if df is None or df_h is None:
                continue

            trend_h = get_trend(df_h)

            result = analyze(df)
            if result is None:
                continue

            trend, strength = result

            if trend != trend_h:
                continue

            trade = build_trade(df, trend)
            if not trade:
                continue

            entry, stop, tp1, tp2, tp3 = trade

            text = "🔥 СИГНАЛ\n" + format_signal(symbol, trend, strength, entry, stop, tp1, tp2, tp3)

            await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text)

        await asyncio.sleep(900)


# === START ===
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))

app.job_queue.run_once(lambda ctx: asyncio.create_task(scan_market(app)), 5)

app.run_polling()

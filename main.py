# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"
ALLOWED_CHAT_ID = -1003130189488

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]


# ================= DATA =================
def get_klines(symbol, interval="15m"):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit=150"
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
            scenario = "Ищем вход в лонг на откате"
        else:
            state = "📉 ШОРТ"
            scenario = "Ищем вход в шорт на откате"

    zone = get_zone(df, trend)

    return state, scenario, high_liq, low_liq, zone, trend, df


# ================= TRADE =================
def build_trade(df, trend, zone):
    if not zone:
        return None

    low, high = zone
    atr = df["atr"].iloc[-1]

    if trend == "LONG":
        entry = low + (high - low) * 0.4
        stop = low - atr * 1.5
        tp1 = entry + atr * 2
        tp2 = entry + atr * 3
        tp3 = entry + atr * 5
    else:
        entry = high - (high - low) * 0.4
        stop = high + atr * 1.5
        tp1 = entry - atr * 2
        tp2 = entry - atr * 3
        tp3 = entry - atr * 5

    return entry, stop, tp1, tp2, tp3


# ================= SIGNAL =================
def strong_signal(df):
    last = df.iloc[-1]

    if last["volume"] < last["vol_ma"] * 1.5:
        return None

    trend = "LONG" if last["ema20"] > last["ema50"] else "SHORT"

    if trend == "LONG" and last["close"] < last["open"]:
        return None
    if trend == "SHORT" and last["close"] > last["open"]:
        return None

    return trend


# ================= USER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    symbol = update.message.text.upper().replace("/USDT","").strip()

    df = get_klines(symbol)
    df_h = get_klines(symbol, "1h")

    if df is None or df_h is None:
        await update.message.reply_text("❌ Монета не найдена")
        return

    state, scenario, high_liq, low_liq, zone, trend, df = analyze(df, df_h)

    text = f"{symbol}/USDT\n\n{state}\n\n"
    text += f"💧 Ликвидность:\nСверху: {round(high_liq,4)}\nСнизу: {round(low_liq,4)}\n\n"
    text += f"📌 Сценарий:\n{scenario}\n\n"

    if zone:
        low, high = zone
        text += f"📍 Зона входа:\n{round(low,4)} - {round(high,4)}\n\n"

    trade = build_trade(df, trend, zone)

    if trade:
        entry, stop, tp1, tp2, tp3 = trade
        price = df["close"].iloc[-1]

        decision = "МОЖНО ВХОДИТЬ" if abs(price - entry) < entry * 0.002 else "ЖДАТЬ"

        text += f"""⚡ Сейчас: {decision}

💰 Сделка:
{"📈 ЛОНГ" if trend=="LONG" else "📉 ШОРТ"}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

🎯 Цели:
TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}

⚠️ Оценивайте риски заходите на 1-2% от депозита
"""

    await update.message.reply_text(text)


# ================= AUTO =================
async def scan_market(app):
    while True:
        for symbol in SYMBOLS:
            df = get_klines(symbol)
            df_h = get_klines(symbol, "1h")

            if df is None or df_h is None:
                continue

            df = add_indicators(df)
            df_h = add_indicators(df_h)

            signal = strong_signal(df)
            if not signal:
                continue

            if signal != get_trend(df_h):
                continue

            zone = get_zone(df, signal)
            trade = build_trade(df, signal, zone)

            if not trade:
                continue

            entry, stop, tp1, tp2, tp3 = trade

            text = f"""🚨 СИГНАЛ {symbol}

{"📈 ЛОНГ" if signal=="LONG" else "📉 ШОРТ"}

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

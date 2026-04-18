# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"
ALLOWED_CHAT_ID = -1003130189488

SYMBOLS = ["BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","LINK","MATIC"]


# ================= STORAGE =================
active_trades = {}

stats = {
    "total": 0,
    "win": 0,
    "loss": 0
}


# ================= DATA =================
def get_binance(symbol, interval):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}USDT&interval={interval}&limit=150"
        data = requests.get(url, timeout=10).json()

        if isinstance(data, dict):
            return None

        df = pd.DataFrame(data)[[0,1,2,3,4,5]]
        df.columns = ["time","open","high","low","close","volume"]
        df = df.astype(float)

        df["time"] = pd.to_datetime(df["time"], unit='ms')
        df.set_index("time", inplace=True)

        return df
    except:
        return None


def get_market(symbol, interval):
    df = get_binance(symbol, interval)
    if df is not None:
        return df, "Binance"
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


# ================= LOGIC =================
def get_zone(df, trend):
    candles = df.tail(12)

    for i in range(len(candles)-1, -1, -1):
        c = candles.iloc[i]

        if trend == "LONG" and c["close"] < c["open"]:
            return c["low"], c["open"]

        if trend == "SHORT" and c["close"] > c["open"]:
            return c["open"], c["high"]

    return None


def is_flat(df):
    atr = df["atr"].iloc[-1]
    avg = (df["high"] - df["low"]).rolling(20).mean().iloc[-1]
    return atr < avg * 0.7


def volume_spike(df):
    last = df.iloc[-1]
    return last["volume"] > last["vol_ma"] * 1.5


def confirm_entry(df, zone, trend):
    if not zone:
        return None

    low, high = zone

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    if trend == "LONG":
        if prev2["low"] < low and prev["close"] > low and last["close"] > prev["high"]:
            return last["close"]

    if trend == "SHORT":
        if prev2["high"] > high and prev["close"] < high and last["close"] < prev["low"]:
            return last["close"]

    return None


def build_trade(df, trend, zone):
    if not zone or is_flat(df) or not volume_spike(df):
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
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return

    text = update.message.text.strip()
    if not text.startswith("/"):
        return

    symbol = text.replace("/", "").upper()

    df, source = get_market(symbol, "15m")
    df_h, _ = get_market(symbol, "1h")

    if df is None or df_h is None:
        await update.message.reply_text("❌ Монета не найдена")
        return

    df = add_indicators(df)
    df_h = add_indicators(df_h)

    trend = get_trend(df)
    higher = get_trend(df_h)

    high_liq = df["high"].rolling(30).max().iloc[-1]
    low_liq = df["low"].rolling(30).min().iloc[-1]

    zone = get_zone(df, trend)

    msg = f"🚀 {symbol}/USDT ({source})\n\n"

    msg += f"📊 Рынок: {'📈 ЛОНГ' if trend==higher else '⚖️ ФЛЭТ'}\n\n"
    msg += f"💧 Ликвидность:\n⬆️ {round(high_liq,4)}\n⬇️ {round(low_liq,4)}\n\n"
    msg += f"📌 Сценарий:\n{'Ищем лонг' if trend=='LONG' else 'Ищем шорт'}\n\n"

    if zone:
        low, high = zone
        entry = (low + high) / 2
        atr = df["atr"].iloc[-1]

        if trend == "LONG":
            stop = low - atr * 1.2
            risk = entry - stop
            tp1 = entry + risk
            tp2 = entry + risk * 2
            tp3 = entry + risk * 4
        else:
            stop = high + atr * 1.2
            risk = stop - entry
            tp1 = entry - risk
            tp2 = entry - risk * 2
            tp3 = entry - risk * 4

        msg += f"📍 Зона: {round(low,4)} - {round(high,4)}\n\n"
        msg += f"""💰 Сделка:
{'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

🎯 TP1: {round(tp1,4)}
🎯 TP2: {round(tp2,4)}
🎯 TP3: {round(tp3,4)}
"""

    msg += "\n⚠️ Оценивайте риски\nВход 1-2% от депозита"

    await update.message.reply_text(msg)


# ================= AUTO SIGNAL =================
async def scan_market(app):
    await asyncio.sleep(10)

    while True:
        for symbol in SYMBOLS:

            df, source = get_market(symbol, "15m")
            df_h, _ = get_market(symbol, "1h")

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

            trade_id = f"{symbol}_{int(pd.Timestamp.now().timestamp())}"

            active_trades[trade_id] = {
                "symbol": symbol,
                "trend": trend,
                "entry": entry,
                "stop": stop,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3
            }

            text = f"""🚨 СИГНАЛ {symbol}

{'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}

Вход: {round(entry,4)}
Стоп: {round(stop,4)}

TP1: {round(tp1,4)}
TP2: {round(tp2,4)}
TP3: {round(tp3,4)}
"""

            await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text)

        await asyncio.sleep(600)


# ================= MONITOR =================
async def monitor_trades(app):
    await asyncio.sleep(20)

    while True:
        remove = []

        for tid, t in active_trades.items():

            df, _ = get_market(t["symbol"], "1m")
            if df is None:
                continue

            price = df["close"].iloc[-1]

            if t["trend"] == "LONG":

                if price <= t["stop"]:
                    stats["total"] += 1
                    stats["loss"] += 1
                    await app.bot.send_message(ALLOWED_CHAT_ID, f"❌ {t['symbol']} SL")
                    remove.append(tid)

                elif price >= t["tp3"]:
                    stats["total"] += 1
                    stats["win"] += 1
                    await app.bot.send_message(ALLOWED_CHAT_ID, f"✅ {t['symbol']} TP3 🚀")
                    remove.append(tid)

            else:

                if price >= t["stop"]:
                    stats["total"] += 1
                    stats["loss"] += 1
                    await app.bot.send_message(ALLOWED_CHAT_ID, f"❌ {t['symbol']} SL")
                    remove.append(tid)

                elif price <= t["tp3"]:
                    stats["total"] += 1
                    stats["win"] += 1
                    await app.bot.send_message(ALLOWED_CHAT_ID, f"✅ {t['symbol']} TP3 🚀")
                    remove.append(tid)

        for r in remove:
            active_trades.pop(r, None)

        await asyncio.sleep(30)


# ================= START =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))


async def on_start(app):
    asyncio.create_task(scan_market(app))
    asyncio.create_task(monitor_trades(app))


app.post_init = on_start

app.run_polling()

# -*- coding: utf-8 -*-

import requests
import pandas as pd
import asyncio
import time
import json
import os
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ================= КОНФИГУРАЦИЯ =================
TOKEN = "8577341778:AAG1vhEXlACi-cdXSpcSpgDtDsJug_F1lIg"          # СЮДА ВСТАВЬ ТОКЕН
ALLOWED_CHAT_ID = -1003130189488    # СЮДА ID ГРУППЫ (с минусом)

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK", "AVAX", "MATIC"]
COOLDOWN_MINUTES = 30
SIGNAL_LIFETIME_HOURS = 4

last_signal_time = {}
last_signal_price = {}
pending_entries = {}
STATS_FILE = "stats.json"

def fmt(p):
    if p < 0.0001: return f"{p:.8f}"
    elif p < 0.01: return f"{p:.6f}"
    elif p < 1: return f"{p:.4f}"
    else: return f"{p:.2f}"

def add_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
    df["atr"] = df["atr"].bfill().ffill()
    return df

def get_trend(df):
    return "LONG" if df.iloc[-1]["ema20"] > df.iloc[-1]["ema50"] else "SHORT"

def get_liquidity_zones(df):
    highs = df["high"].tail(50)
    lows = df["low"].tail(50)
    current_price = df["close"].iloc[-1]
    if current_price < 0.01: decimals = 6
    elif current_price < 1: decimals = 4
    else: decimals = 2
    highs_rounded = highs.round(decimals)
    lows_rounded = lows.round(decimals)
    high_counts = highs_rounded.value_counts()
    low_counts = lows_rounded.value_counts()
    high_levels = high_counts[high_counts >= 2].index.tolist()
    low_levels = low_counts[low_counts >= 2].index.tolist()
    top_liq = max(high_levels) if high_levels else highs.max()
    bottom_liq = min(low_levels) if low_levels else lows.min()
    return top_liq, bottom_liq

def get_zone(df, direction):
    for _, c in df.tail(12).iloc[::-1].iterrows():
        if direction == "LONG" and c["close"] < c["open"]:
            return (c["low"], c["open"])
        if direction == "SHORT" and c["close"] > c["open"]:
            return (c["open"], c["high"])
    return None

def confirm_entry(df, zone, direction):
    if not zone: return None
    low, high = zone
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if direction == "LONG":
        if last["close"] > prev["high"]:
            return last["close"]
    else:
        if last["close"] < prev["low"]:
            return last["close"]
    return None

def get_binance(symbol, interval):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}USDT&interval={interval}&limit=150"
        data = requests.get(url, timeout=10).json()
        if isinstance(data, dict) and 'code' in data: return None
        df = pd.DataFrame(data)[[0,1,2,3,4,5]]
        df.columns = ["time","open","high","low","close","volume"]
        df = df.astype(float)
        df["time"] = pd.to_datetime(df["time"], unit='ms')
        df.set_index("time", inplace=True)
        return df
    except: return None

async def coin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    text = update.message.text.strip()
    if not text.startswith("/"): return
    symbol = text.replace("/", "").upper()
    if symbol in ["STATS", "EXPORT", "HELP", "START"]: return

    df = get_binance(symbol, "15m")
    df_h = get_binance(symbol, "1h")
    if df is None or df_h is None:
        await update.message.reply_text("❌ Монета не найдена")
        return

    df = add_indicators(df)
    df_h = add_indicators(df_h)

    trend = get_trend(df)
    trend_h = get_trend(df_h)
    if trend != trend_h:
        await update.message.reply_text("⚠️ Тренды на 15m и 1h не совпадают. Ждите.")
        return

    zone = get_zone(df, trend)
    if not zone:
        await update.message.reply_text("❌ Нет зоны входа")
        return

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

    status = confirm_entry(df, zone, trend)
    high_liq, low_liq = get_liquidity_zones(df)

    msg = f"""🚀 {symbol}/USDT (Binance)

📊 Рынок: {'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}

💧 Ликвидность:
⬆️ {fmt(high_liq)}
⬇️ {fmt(low_liq)}

📍 Зона входа: {fmt(low)} - {fmt(high)}
⚡ Сейчас: {'✅ МОЖНО ВХОДИТЬ' if status else '⏳ ЖДАТЬ'}

💰 Вход: {fmt(entry)} | Стоп: {fmt(stop)}
🎯 TP1: {fmt(tp1)} | TP2: {fmt(tp2)} | TP3: {fmt(tp3)}

⚠️ Вход 1-2% от депозита
"""
    await update.message.reply_text(msg)

    if not status:
        expires_at = time.time() + SIGNAL_LIFETIME_HOURS * 3600
        pending_entries[symbol] = {
            "zone_low": low, "zone_high": high, "trend": trend,
            "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "chat_id": update.effective_chat.id, "expires_at": expires_at
        }
        await update.message.reply_text(f"🔄 Буду следить за {symbol} до входа в зону.")

async def check_entries(app):
    await asyncio.sleep(30)
    while True:
        for symbol, data in list(pending_entries.items()):
            if time.time() > data["expires_at"]:
                del pending_entries[symbol]
                continue
            df = get_binance(symbol, "15m")
            if df is None: continue
            df = add_indicators(df)
            current_price = df["close"].iloc[-1]
            if data["zone_low"] <= current_price <= data["zone_high"]:
                await app.bot.send_message(
                    chat_id=data["chat_id"],
                    text=f"""🚨 СИГНАЛ! {symbol}/USDT 🚨

✅ ЦЕНА ВОШЛА В ЗОНУ!

📍 Зона: {fmt(data['zone_low'])} - {fmt(data['zone_high'])}
💰 Текущая цена: {fmt(current_price)}

🎯 Вход: {fmt(data['entry'])} | Стоп: {fmt(data['stop'])}
🎯 TP1: {fmt(data['tp1'])} | TP2: {fmt(data['tp2'])} | TP3: {fmt(data['tp3'])}

⚡ ДЕЙСТВУЙ!
"""
                )
                del pending_entries[symbol]
        await asyncio.sleep(60)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    await update.message.reply_text("📚 /BTC - анализ монеты\n/stats - статистика\n/help - помощь")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    await help_cmd(update, context)

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start_cmd))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(MessageHandler(filters.COMMAND, coin_handler))

async def on_start(app):
    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text="🤖 Бот запущен!")
    asyncio.create_task(check_entries(app))

app.post_init = on_start

if __name__ == "__main__":
    app.run_polling()

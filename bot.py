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
TOKEN = "8577341778:AAG1vhEXlACi-cdXSpcSpgDtDsJug_F1lIg"
ALLOWED_CHAT_ID = -1003130189488

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK", "AVAX", "MATIC"]
COOLDOWN_MINUTES = 30
SIGNAL_LIFETIME_HOURS = 4
AUTO_EXCHANGE = "binance"

last_signal_time = {}
last_signal_price = {}
pending_entries = {}

STATS_FILE = "stats.json"
AUTO_STATS_FILE = "auto_stats.json"

# ================= ФОРМАТ =================
def fmt(p):
    if p < 0.0001: return f"{p:.8f}"
    elif p < 0.01: return f"{p:.6f}"
    elif p < 1: return f"{p:.4f}"
    else: return f"{p:.2f}"

# ================= ИНДИКАТОРЫ =================
def add_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
    df["atr"] = df["atr"].bfill().ffill()
    return df

def get_trend(df):
    return "LONG" if df.iloc[-1]["ema20"] > df.iloc[-1]["ema50"] else "SHORT"

# ================= ЛИКВИДНОСТЬ =================
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

# ================= ЗОНА =================
def get_zone(df, direction):
    for _, c in df.tail(12).iloc[::-1].iterrows():
        if direction == "LONG" and c["close"] < c["open"]:
            return (c["low"], c["open"])
        if direction == "SHORT" and c["close"] > c["open"]:
            return (c["open"], c["high"])
    return None

def confirm_entry(df, zone, direction):
    if zone is None: return None
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

def calculate_recommended_leverage(volatility, trends_match):
    if volatility < 1.5:
        base = 10
    elif volatility < 3.0:
        base = 5
    else:
        base = 3
    if trends_match == 2:
        base = int(base * 1.3)
    elif trends_match == 1:
        base = int(base * 1.1)
    return min(max(base, 1), 20)

# ================= МУЛЬТИБИРЖА =================
def get_binance(symbol, interval):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}USDT&interval={interval}&limit=150"
        data = requests.get(url, timeout=10).json()
        if isinstance(data, dict) and 'code' in data:
            return None
        df = pd.DataFrame(data)[[0,1,2,3,4,5]]
        df.columns = ["time","open","high","low","close","volume"]
        df = df.astype(float)
        df["time"] = pd.to_datetime(df["time"], unit='ms')
        df.set_index("time", inplace=True)
        return df
    except Exception:
        return None

def get_bybit(symbol, interval):
    try:
        interval_map = {"1m":"1","5m":"5","15m":"15","1h":"60","4h":"240"}
        bybit_interval = interval_map.get(interval, "15")
        url = "https://api.bybit.com/v5/market/kline"
        params = {"category":"linear","symbol":f"{symbol}USDT","interval":bybit_interval,"limit":150}
        data = requests.get(url, params=params, timeout=10).json()
        if data.get("retCode") != 0:
            return None
        klines = data["result"]["list"]
        df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume","turnover"])
        df = df.astype(float)
        df["time"] = pd.to_datetime(df["time"].astype(float), unit='ms')
        df.set_index("time", inplace=True)
        return df
    except Exception:
        return None

def get_okx(symbol, interval):
    try:
        interval_map = {"1m":"1m","5m":"5m","15m":"15m","1h":"1H","4h":"4H"}
        okx_interval = interval_map.get(interval, "15m")
        url = "https://www.okx.com/api/v5/market/candles"
        params = {"instId":f"{symbol}-USDT-SWAP","bar":okx_interval,"limit":"150"}
        data = requests.get(url, params=params, timeout=10).json()
        if data.get("code") != "0":
            return None
        candles = data["data"]
        df = pd.DataFrame(candles, columns=["time","open","high","low","close","volCcy","vol","volCcyQuote","confirm"])
        df = df.astype(float)
        df["time"] = pd.to_datetime(df["time"].astype(float), unit='ms')
        df.set_index("time", inplace=True)
        df["volume"] = df["vol"]
        return df
    except Exception:
        return None

def get_market(symbol, tf, exchange="binance"):
    if exchange == "binance":
        return get_binance(symbol, tf), "Binance"
    elif exchange == "bybit":
        return get_bybit(symbol, tf), "Bybit"
    elif exchange == "okx":
        return get_okx(symbol, tf), "OKX"
    else:
        return get_binance(symbol, tf), "Binance"

def get_market_multi(symbol, tf, preferred="binance"):
    exchanges = ["binance","bybit","okx"]
    if preferred in exchanges:
        exchanges.remove(preferred)
        exchanges.insert(0, preferred)
    for ex in exchanges:
        df, name = get_market(symbol, tf, ex)
        if df is not None:
            return df, name
    return None, None

# ================= СТАТИСТИКА =================
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {"total":0,"tp1":0,"tp2":0,"tp3":0,"sl":0}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

stats = load_stats()

def load_auto_stats():
    if os.path.exists(AUTO_STATS_FILE):
        with open(AUTO_STATS_FILE, "r") as f:
            return json.load(f)
    return {"total":0,"tp1":0,"tp2":0,"tp3":0,"sl":0,"pending":{}}

def save_auto_stats(stats):
    with open(AUTO_STATS_FILE, "w") as f:
        json.dump(stats, f)

auto_stats = load_auto_stats()
signal_counter = 0

def generate_signal_id():
    global signal_counter
    signal_counter += 1
    return int(time.time()*1000) + signal_counter

# ================= БЛОК 1: АНАЛИЗ =================
async def coin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    text = update.message.text.strip()
    if not text.startswith("/"):
        return
    parts = text.split()
    symbol = parts[0].replace("/", "").upper()
    preferred_exchange = parts[1].lower() if len(parts) > 1 else "binance"
    if preferred_exchange not in ["binance","bybit","okx"]:
        preferred_exchange = "binance"
    if symbol in ["STATS","EXPORT","HELP","START","AUTOSTATS","ADD","RESET_STATS"]:
        return

    df, source = get_market_multi(symbol, "15m", preferred_exchange)
    df_h, _ = get_market_multi(symbol, "1h", preferred_exchange)
    df_4h, _ = get_market_multi(symbol, "4h", preferred_exchange)

    if df is None or df_h is None:
        await update.message.reply_text(f"❌ Монета {symbol} не найдена на {preferred_exchange}")
        return

    df = add_indicators(df)
    df_h = add_indicators(df_h)
    if df_4h is not None:
        df_4h = add_indicators(df_4h)

    trend = get_trend(df)
    trend_h = get_trend(df_h)
    trend_4h = get_trend(df_4h) if df_4h is not None else trend

    trends_match = sum([trend == trend_h, trend == trend_4h])
    strength_emoji = "🔥🔥🔥" if trends_match == 2 else "🔥🔥" if trends_match == 1 else "🔥"

    zone = get_zone(df, trend)
    if zone is None:
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
    volatility = (atr / entry) * 100
    rec_leverage = calculate_recommended_leverage(volatility, trends_match)

    trends_agree = (trend == trend_h)
    if status and trends_agree:
        now_status = "✅ МОЖНО ВХОДИТЬ"
    elif not status and trends_agree:
        now_status = "⏳ ЖДАТЬ"
    else:
        now_status = "⏳ ЖДАТЬ (тренды 15m и 1h не совпадают)"

    trend_line = f"📈 Тренды: 15m {trend} | 1h {trend_h} | 4h {trend_4h}"

    msg = f"""🚀 {symbol}/USDT ({source})

📊 Рынок: {'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}
{trend_line}
💪 Сила тренда: {strength_emoji}

💧 Ликвидность:
⬆️ {fmt(high_liq)}
⬇️ {fmt(low_liq)}

📍 Зона входа:
{fmt(low)} - {fmt(high)}

⚡ Сейчас: {now_status}

💰 Сделка:
{'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}

Вход: {fmt(entry)}
Стоп: {fmt(stop)}

🎯 TP1: {fmt(tp1)}
🎯 TP2: {fmt(tp2)}
🎯 TP3: {fmt(tp3)}

📊 Волатильность: {volatility:.2f}%

🦿 Рекомендуемое плечо: {rec_leverage}x

⚠️ Вход не более 1-2% от депозита. Оценивайте свои финансовые риски.
"""
    await update.message.reply_text(msg)

    if not status:
        expires_at = time.time() + SIGNAL_LIFETIME_HOURS * 3600
        pending_entries[symbol] = {
            "zone_low": low, "zone_high": high, "trend": trend,
            "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "chat_id": update.effective_chat.id,
            "expires_at": expires_at,
            "exchange": source
        }
        await update.message.reply_text(f"🔄 Буду следить за {symbol} до входа в зону.")

# ================= БЛОК 2: ОТСЛЕЖИВАНИЕ ВХОДА =================
async def check_entries(app):
    await asyncio.sleep(30)
    while True:
        for symbol, data in list(pending_entries.items()):
            if time.time() > data["expires_at"]:
                del pending_entries[symbol]
                continue
            df = get_binance(symbol, "15m")
            if df is None:
                continue
            df = add_indicators(df)
            current_trend = get_trend(df)
            if current_trend != data["trend"]:
                await app.bot.send_message(
                    chat_id=data["chat_id"],
                    text=f"⚠️ Тренд на 15m изменился! {symbol}\nБыл: {'📈 ЛОНГ' if data['trend']=='LONG' else '📉 ШОРТ'}\nСтал: {'📈 ЛОНГ' if current_trend=='LONG' else '📉 ШОРТ'}\nНапишите /{symbol} для нового анализа"
                )
                del pending_entries[symbol]
                continue
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

⚠️ Вход не более 1-2% от депозита. Оценивайте свои финансовые риски.
"""
                )
                del pending_entries[symbol]
        await asyncio.sleep(60)

# ================= БЛОК 3: АВТОСИГНАЛЫ =================
async def scan_market(app):
    await asyncio.sleep(30)
    while True:
        for symbol in SYMBOLS:
            try:
                df, source = get_market_multi(symbol, "15m", AUTO_EXCHANGE)
                df_h, _ = get_market_multi(symbol, "1h", AUTO_EXCHANGE)
                df_4h, _ = get_market_multi(symbol, "4h", AUTO_EXCHANGE)
                if df is None or df_h is None or df_4h is None:
                    continue

                df = add_indicators(df)
                df_h = add_indicators(df_h)
                df_4h = add_indicators(df_4h)

                trend = get_trend(df)
                trend_h = get_trend(df_h)
                trend_4h = get_trend(df_4h)
                if trend != trend_h:
                    continue

                trends_match = sum([trend == trend_h, trend == trend_4h])
                if trends_match == 2:
                    strength = "🔥🔥🔥 СИЛЬНЫЙ (3/3)"
                    strength_score = 3
                    min_vol_ratio = 1.3
                elif trends_match == 1:
                    strength = "🔥🔥 СРЕДНИЙ (2/3)"
                    strength_score = 2
                    min_vol_ratio = 1.5
                else:
                    strength = "🔥 СЛАБЫЙ (1/3)"
                    strength_score = 1
                    min_vol_ratio = 2.0

                zone = get_zone(df, trend)
                if zone is None:
                    continue
                entry_confirm = confirm_entry(df, zone, trend)
                if not entry_confirm:
                    continue

                now = time.time()
                if symbol in last_signal_time and now - last_signal_time[symbol] < COOLDOWN_MINUTES * 60:
                    continue
                current_price = df["close"].iloc[-1]
                if symbol in last_signal_price:
                    price_change = abs(current_price - last_signal_price[symbol]) / last_signal_price[symbol] * 100
                    if price_change < 0.5:
                        continue

                avg_volume = df["volume"].tail(20).mean()
                curr_vol = df["volume"].iloc[-1]
                if curr_vol < avg_volume * min_vol_ratio:
                    continue

                low, high = zone
                entry_price = (low + high) / 2
                atr = df["atr"].iloc[-1]

                if trend == "LONG":
                    stop = low - atr * 2.0
                    risk = entry_price - stop
                    tp1 = entry_price + risk * 1.5
                    tp2 = entry_price + risk * 2.5
                    tp3 = entry_price + risk * 4.0
                else:
                    stop = high + atr * 2.0
                    risk = stop - entry_price
                    tp1 = entry_price - risk * 1.5
                    tp2 = entry_price - risk * 2.5
                    tp3 = entry_price - risk * 4.0

                signal_id = generate_signal_id()
                auto_stats["pending"][signal_id] = {
                    "symbol": symbol, "entry": entry_price, "stop": stop, "trend": trend,
                    "timestamp": now, "signal_time": now, "strength": strength_score
                }
                save_auto_stats(auto_stats)

                last_signal_time[symbol] = now
                last_signal_price[symbol] = current_price

                await app.bot.send_message(
                    chat_id=ALLOWED_CHAT_ID,
                    text=f"""🚨 АВТОСИГНАЛ! {symbol}/USDT 🚨

📍 Источник: {source}
📊 Тренд: {'📈 ЛОНГ' if trend=='LONG' else '📉 ШОРТ'}
💪 Сила сигнала: {strength}

✅ ТОЧКА ВХОДА!

💰 Вход: {fmt(entry_price)}
⚠️ Стоп: {fmt(stop)}

🎯 TP1: {fmt(tp1)}
🎯 TP2: {fmt(tp2)}
🎯 TP3: {fmt(tp3)}

📊 Объём: +{((curr_vol/avg_volume)-1)*100:.0f}%
🆔 ID: {signal_id}

⚠️ Вход не более 1-2% от депозита. Оценивайте свои финансовые риски.
"""
                )
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
        await asyncio.sleep(180)

# ================= АВТОСТАТИСТИКА =================
async def check_signal_result(app):
    await asyncio.sleep(60)
    while True:
        now = time.time()
        for sid, data in list(auto_stats.get("pending", {}).items()):
            symbol = data["symbol"]
            entry = data["entry"]
            stop = data["stop"]
            trend = data["trend"]
            signal_time = data.get("signal_time", data["timestamp"])
            if now - signal_time > 86400:
                del auto_stats["pending"][sid]
                save_auto_stats(auto_stats)
                continue

            df, _ = get_market(symbol, "1h", AUTO_EXCHANGE)
            if df is None:
                continue
            df = add_indicators(df)
            current_price = df["close"].iloc[-1]

            if trend == "LONG":
                tp1 = entry + (entry - stop) * 1.5
                tp2 = entry + (entry - stop) * 2.5
                tp3 = entry + (entry - stop) * 4.0
                if current_price >= tp3:
                    auto_stats["tp3"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP3!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price >= tp2:
                    auto_stats["tp2"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP2!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price >= tp1:
                    auto_stats["tp1"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP1!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price <= stop:
                    auto_stats["sl"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"❌ АВТОСИГНАЛ {symbol} СРАБОТАЛ СТОП!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
            else:
                tp1 = entry - (stop - entry) * 1.5
                tp2 = entry - (stop - entry) * 2.5
                tp3 = entry - (stop - entry) * 4.0
                if current_price <= tp3:
                    auto_stats["tp3"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP3!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price <= tp2:
                    auto_stats["tp2"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP2!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price <= tp1:
                    auto_stats["tp1"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"🎯 АВТОСИГНАЛ {symbol} ДОСТИГ TP1!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
                elif current_price >= stop:
                    auto_stats["sl"] += 1
                    auto_stats["total"] += 1
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=f"❌ АВТОСИГНАЛ {symbol} СРАБОТАЛ СТОП!\n💰 Вход: {fmt(entry)} → {fmt(current_price)}")
                    del auto_stats["pending"][sid]
            save_auto_stats(auto_stats)
        await asyncio.sleep(300)

# ================= КОМАНДЫ =================
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    if stats["total"] == 0:
        await update.message.reply_text("📊 Нет данных по сделкам")
        return
    t = stats["total"]
    winrate = (stats['tp1']+stats['tp2']+stats['tp3'])/t*100
    msg = f"""📊 СТАТИСТИКА СИГНАЛОВ
━━━━━━━━━━━━━━━━━━━
📈 Всего: {t}
✅ Винрейт: {winrate:.1f}%
🎯 TP1: {stats['tp1']} ({stats['tp1']/t*100:.1f}%)
🎯 TP2: {stats['tp2']} ({stats['tp2']/t*100:.1f}%)
🎯 TP3: {stats['tp3']} ({stats['tp3']/t*100:.1f}%)
❌ SL: {stats['sl']} ({stats['sl']/t*100:.1f}%)"""
    await update.message.reply_text(msg)

async def add_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ Использование: /add TP1 BTC")
        return
    result, symbol = args[0].upper(), args[1].upper()
    global stats
    if result == "TP1":
        stats["tp1"] += 1
        stats["total"] += 1
        msg = f"✅ Записан TP1 по {symbol}"
    elif result == "TP2":
        stats["tp2"] += 1
        stats["total"] += 1
        msg = f"✅ Записан TP2 по {symbol}"
    elif result == "TP3":
        stats["tp3"] += 1
        stats["total"] += 1
        msg = f"✅ Записан TP3 по {symbol}"
    elif result == "SL":
        stats["sl"] += 1
        stats["total"] += 1
        msg = f"❌ Записан SL по {symbol}"
    else:
        await update.message.reply_text("❌ Неверно. Используйте: TP1, TP2, TP3, SL")
        return
    save_stats(stats)
    await update.message.reply_text(msg)
    await stats_cmd(update, context)

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    if os.path.exists(STATS_FILE):
        await update.message.reply_document(document=open(STATS_FILE,"rb"), filename="stats.json")
    else:
        await update.message.reply_text("Нет файла")

async def reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    global stats
    stats = {"total":0,"tp1":0,"tp2":0,"tp3":0,"sl":0}
    save_stats(stats)
    await update.message.reply_text("🗑 Статистика сброшена!")

async def auto_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    total = auto_stats["total"]
    if total == 0:
        await update.message.reply_text("🤖 Нет автосигналов")
        return
    winrate = (auto_stats['tp1']+auto_stats['tp2']+auto_stats['tp3'])/total*100
    msg = f"""🤖 СТАТИСТИКА АВТОСИГНАЛОВ
━━━━━━━━━━━━━━━━━━━
📈 Всего: {total}
✅ Винрейт: {winrate:.1f}%
⏳ Активных: {len(auto_stats.get('pending',{}))}
🎯 TP1: {auto_stats['tp1']} ({auto_stats['tp1']/total*100:.1f}%)
🎯 TP2: {auto_stats['tp2']} ({auto_stats['tp2']/total*100:.1f}%)
🎯 TP3: {auto_stats['tp3']} ({auto_stats['tp3']/total*100:.1f}%)
❌ SL: {auto_stats['sl']} ({auto_stats['sl']/total*100:.1f}%)"""
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    await update.message.reply_text(
        "📚 КОМАНДЫ БОТА\n\n"
        "/BTC (или любая монета) - анализ\n"
        "/stats - статистика ручных сигналов\n"
        "/autostats - статистика автосигналов\n"
        "/add TP1 BTC - добавить результат\n"
        "/export - выгрузить stats.json\n"
        "/reset_stats - сбросить ручную статистику\n"
        "/help - помощь"
    )

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    await help_cmd(update, context)

# ================= ЗАПУСК =================
app = ApplicationBuilder().token(TOKEN).connect_timeout(30).read_timeout(30).build()
app.add_handler(CommandHandler("start", start_cmd))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("stats", stats_cmd))
app.add_handler(CommandHandler("autostats", auto_stats_cmd))
app.add_handler(CommandHandler("add", add_result))
app.add_handler(CommandHandler("export", export_cmd))
app.add_handler(CommandHandler("reset_stats", reset_stats))
app.add_handler(MessageHandler(filters.COMMAND, coin_handler))

async def on_start(app):
    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text="🤖 Бот запущен! Автосигналы активны.")
    asyncio.create_task(check_entries(app))
    asyncio.create_task(scan_market(app))
    asyncio.create_task(check_signal_result(app))

app.post_init = on_start

if __name__ == "__main__":
    app.run_polling()

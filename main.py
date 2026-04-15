import matplotlib
matplotlib.use('Agg')

import requests
import pandas as pd
import matplotlib.pyplot as plt

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"


# === Поиск символа ===
def find_symbol(user_input):
    url = "https://api.binance.com/api/v3/exchangeInfo"
    data = requests.get(url).json()

    symbols = [s["symbol"] for s in data["symbols"]]
    user_input = user_input.upper()

    if user_input + "USDT" in symbols:
        return user_input

    for s in symbols:
        if user_input in s:
            return s.replace("USDT", "")

    return None


# === Свечи ===
def get_klines(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=100"
    res = requests.get(url).json()

    if isinstance(res, dict) and "code" in res:
        return None

    df = pd.DataFrame(res)
    df = df[[0,1,2,3,4,5]]
    df.columns = ["time","open","high","low","close","volume"]

    df = df.astype(float)

    df["time"] = pd.to_datetime(df["time"], unit='ms')
    df.set_index("time", inplace=True)

    return df


# === Анализ ===
def analyze(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    last = df.iloc[-1]
    price = float(last["close"])

    if last["ema20"] > last["ema50"]:
        direction = "📈 ЛОНГ"
        reason = "Восходящий тренд (EMA20 > EMA50)"
    else:
        direction = "📉 ШОРТ"
        reason = "Нисходящий тренд (EMA20 < EMA50)"

    return price, direction, reason


# === ATR уровни ===
def calculate_levels(df, price, direction):
    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

    if direction == "📈 ЛОНГ":
        stop = price - atr * 1.5
        tp1 = price + atr * 1
        tp2 = price + atr * 2
        tp3 = price + atr * 3
    else:
        stop = price + atr * 1.5
        tp1 = price - atr * 1
        tp2 = price - atr * 2
        tp3 = price - atr * 3

    return stop, tp1, tp2, tp3


# === КРАСИВЫЙ ГРАФИК БЕЗ mplfinance ===
def create_chart(df):
    try:
        plt.figure(figsize=(10,5))

        # свечи (упрощённые)
        for i in range(len(df)):
            open_price = df["open"].iloc[i]
            close_price = df["close"].iloc[i]
            high = df["high"].iloc[i]
            low = df["low"].iloc[i]

            color = 'green' if close_price > open_price else 'red'

            # тело свечи
            plt.plot([i, i], [low, high], color=color)
            plt.plot([i, i], [open_price, close_price], linewidth=4, color=color)

        # EMA линии
        plt.plot(df["close"].ewm(span=20).mean(), linewidth=1)
        plt.plot(df["close"].ewm(span=50).mean(), linewidth=1)

        plt.title("Market Structure")
        plt.grid(False)
TP1: {round(tp1, 4)}
TP2: {round(tp2, 4)}
TP3: {round(tp3, 4)}

Почему:
{reason}

Таймфрейм: 15m

Риск: 1-2% от депозита

 —————————————
 Оценивайте свои финансовые возможности и риски
        """

        await update.message.reply_text(text)

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text("⚠️ Ошибка анализа")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle_message))

app.run_polling()

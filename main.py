import requests

import pandas as pd

import mplfinance as mpf



from telegram import Update

from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes



TOKEN = "ТВОЙ_ТОКЕН"





# === Получаем свечи ===

def get_klines(symbol):

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=100"

    data = requests.get(url).json()



    df = pd.DataFrame(data)

    df = df[[0,1,2,3,4,5]]

    df.columns = ["time","open","high","low","close","volume"]



    df["open"] = df["open"].astype(float)

    df["high"] = df["high"].astype(float)

    df["low"] = df["low"].astype(float)

    df["close"] = df["close"].astype(float)



    df["time"] = pd.to_datetime(df["time"], unit='ms')

    df.set_index("time", inplace=True)



    return df





# === Анализ ===

def analyze(df):

    df["ema20"] = df["close"].ewm(span=20).mean()

    df["ema50"] = df["close"].ewm(span=50).mean()



    last = df.iloc[-1]



    if last["ema20"] > last["ema50"]:

        direction = "🟢 ЛОНГ"

        reason = "Тренд вверх (EMA20 выше EMA50)"

    else:

        direction = "🔴 ШОРТ"

        reason = "Тренд вниз (EMA20 ниже EMA50)"



    price = last["close"]



    return price, direction, reason





# === График ===

def create_chart(df):

    mpf.plot(

        df,

        type='candle',

        mav=(20,50),

        volume=True,

        savefig='chart.png'

    )





# === Обработка сообщений ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    symbol = update.message.text.upper()



    try:

        df = get_klines(symbol)



        price, direction, reason = analyze(df)



        entry = round(price, 2)

        stop = round(price * 0.98, 2)



        tp1 = round(price * 1.01, 2)

        tp2 = round(price * 1.02, 2)

        tp3 = round(price * 1.03, 2)



        text = f"""

📊 {symbol}/USDT

📌 {direction}

💰 Цена: {price}

📍 Вход: {entry}

🛑 Стоп: {stop}

🎯 Тейки:

• 50% → {tp1}

• 30% → {tp2}

• 20% → {tp3}
🧠 Почему:
{reason}
⚠️ Риск: 1-2% от депозита
—————————————

• Оценивайте свои финансовые возможности и риски

        """



        await update.message.reply_text(text)



        create_chart(df)



        with open("chart.png", "rb") as img:

            await update.message.reply_photo(img)



    except:

        await update.message.reply_text("❌ Монета не найдена (пример: BTC, ETH, SOL)")





app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))



app.run_polling()

import requests

import pandas as pd

import mplfinance as mpf



from telegram import Update

from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes



TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"





# === Получение свечей с проверкой ===

def get_klines(symbol):

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=100"

    res = requests.get(url).json()



    # ❗ проверка ошибки Binance

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

        stop = price * 0.98

        tp1 = price * 1.01

        tp2 = price * 1.02

        tp3 = price * 1.03

        reason = "Тренд вверх (EMA20 выше EMA50)"

    else:

        direction = "📉 ШОРТ"

        stop = price * 1.02

        tp1 = price * 0.99

        tp2 = price * 0.98

        tp3 = price * 0.97

        reason = "Тренд вниз (EMA20 ниже EMA50)"



    return price, direction, stop, tp1, tp2, tp3, reason





# === График ===

def create_chart(df):
    mc = mpf.make_marketcolors(
        up='green',
        down='red',
        wick='inherit',
        edge='inherit'
    )

    style = mpf.make_mpf_style(
        base_mpf_style='nightclouds',
        marketcolors=mc,
        gridstyle='',
        facecolor='#0f172a'
    )

    mpf.plot(
        df,
        type='candle',
        mav=(20,50),
        volume=True,
        style=style,
        figsize=(10,6),
        tight_layout=True,
        savefig='chart.png'
    )


# === Обработка сообщений ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    symbol = update.message.text.upper()



    df = get_klines(symbol)



    # ❗ если монеты нет

    if df is None or df.empty:

        await update.message.reply_text("❌ Монета не найдена (пример: BTC, ETH, SOL)")

        return



    try:

        price, direction, stop, tp1, tp2, tp3, reason = analyze(df)



        text = f"""

📊 {symbol}/USDT

📌 {direction}

💰 Цена: {round(price, 4)}

📍 Вход: {round(price, 4)}

🛑 Стоп: {round(stop, 4)}


🎯 Тейки:

• 50% → {round(tp1, 4)}

• 30% → {round(tp2, 4)}

• 20% → {round(tp3, 4)}

🧠 Почему:

{reason}

⚠️ Риск: 1-2% от депозита

—————————————

• Оценивайте свои финансовые возможности и риски

        """



        await update.message.reply_text(text)



        # график

        if create_chart(df):

            with open("chart.png", "rb") as img:

                await update.message.reply_photo(img),caption = f"{symbol}/USDT")

await update.message.reply_text(text)

    except Exception as e:

        await update.message.reply_text("⚠️ Ошибка анализа")





app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))



app.run_polling()


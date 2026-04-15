import matplotlib
matplotlib.use('Agg')
import requests

import pandas as pd

import mplfinance as mpf



from telegram import Update

from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes



TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"



def find_symbol(user_input):
    url = "https://api.binance.com/api/v3/exchangeInfo"
    data = requests.get(url).json()

    symbols = [s["symbol"] for s in data["symbols"]]

    user_input = user_input.upper()

    # прямое совпадение
    if user_input + "USDT" in symbols:
        return user_input

    # поиск похожего
    for s in symbols:
        if user_input in s:
            return s.replace("USDT", "")

    return None

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

def calculate_levels(df,price,direction):rolling(14).mean().iloc[-1]
    atr = (df["hight"] - df["low"]).rolling(14).mean().iloc[-1]


    if direction == "📈 ЛОНГ"

        stop = price - atr * 1.5

        tp1 = price + atr * 1

        tp2 = price + atr * 2

        tp3 = price + atr * 3

    else:

        direction = "📉 ШОРТ"

        stop = price + atr * 1.5

        tp1 = price - atr * 1

        tp2 = price - atr * 2

        tp3 = price - atr * 3

        reason = "Тренд вниз (EMA20 ниже EMA50)"



    return price, direction, reason = analyze(df)
    stop, tp1, tp2, tp3 = calculate_levels(df,price,direction)





# === График ===
import matplotlib.pyplot as plt
def create_chart(df):
    try:
        plt.figure(figsize=(10,5))
        plt.plot(df["close"])
        plt.title("Price Chart")

        plt.savefig("chart.png")
        plt.close()
        return True


    except Exception as e:
        print("CHART ERROR:", e)
        return False


# === Обработка сообщений ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.upper()
    symbol = find_symbol(user_input)
    if symbol is None:
        await update.message.reply_text("❌ Монета не найдена")
        return

    df = get_klines(symbol)

    if df is None or df.empty:
        await update.message.reply_text("❌ Монета не найдена")
        return

    try:
        price, direction, stop, tp1, tp2, tp3, reason = analyze(df)

        # 📊 график сначала
        create_chart(df)

try:
    with open("chart.png", "rb") as img:
        await update.message.reply_photo(img)
except Exception as e:
    print("SEND ERROR:", e)

        # 📩 потом текст
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

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text("⚠️ Ошибка анализа")






app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT, handle_message))



app.run_polling()


print("BOT STARTING..."
import requests

import pandas as pd

import matplotlib.pyplot as plt



from telegram import Update

from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes



TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"





# === Получение цены ===

def get_price(symbol):

    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"

    data = requests.get(url).json()



    if "price" not in data:

        return None



    return float(data["price"])





# === Анализ ===

def analyze(symbol):

    price = get_price(symbol)



    if price is None:

        return None



    # Простая логика

    if price % 2 > 1:

        direction = "📈 ЛОНГ"

        reason = "Покупатели активнее, есть вероятность роста"

    else:

        direction = "📉 ШОРТ"

        reason = "Продавцы давят, возможна коррекция"



    return price, direction, reason





# === График (имитация ликвидаций) ===

def create_plot(price):

    levels = [price * 0.97, price * 0.99, price, price * 1.01, price * 1.03]

    volumes = [10, 50, 20, 60, 15]



    plt.figure()

    plt.bar(levels, volumes)



    plt.title("Liquidity Heatmap (пример)")

    plt.savefig("plot.png")

    plt.close()





# === Обработка текста ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    symbol = update.message.text.upper()



    result = analyze(symbol)



    if result is None:

        await update.message.reply_text("❌ Монета не найдена, попробуй BTC или ETH")

        return



    price, direction, reason = result



    entry = price

    stop = round(price * 0.98, 2)



    tp1 = round(price * 1.01, 2)

    tp2 = round(price * 1.02, 2)

    tp3 = round(price * 1.03, 2)



    text = f"""

📊 {symbol}/USDT



💰 Цена: {price}



📌 Направление: {direction}



📍 Вход: {entry}

🛑 Стоп: {stop}



🎯 Тейки:

1️⃣ {tp1}

2️⃣ {tp2}

3️⃣ {tp3}



🧠 Почему:

{reason}



⚠️ Риск: не более 1-2% от депозита



—————————————

• Оценивайте свои финансовые возможности и риски

    """



    await update.message.reply_text(text)



    create_plot(price)



    with open("plot.png", "rb") as img:

        await update.message.reply_photo(img)





app = ApplicationBuilder().token(TOKEN).build()



app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))



app.run_polling()
print("BOT RUNNING...)

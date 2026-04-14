import requests

import pandas as pd



from telegram import Update

from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes



TOKEN = "8773850466:AAF0ZYcuNusn9R8TzyxQRCZoY2Nz2pg6MiA"



def get_price(symbol):

    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"

    data = requests.get(url).json()

    return float(data["price"])



async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text("Пример: /analyze BTCUSDT")

        return



    symbol = context.args[0].upper()



    try:

        price = get_price(symbol)



        text = f"""

📊 {symbol}



Цена: {price}



📍 Вход: {price}

🛑 Стоп: {round(price * 0.98, 2)}

🎯 Тейк: {round(price * 1.03, 2)}

        """



        await update.message.reply_text(text)



    except:

        await update.message.reply_text("Ошибка, проверь тикер")



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("Напиши /analyze BTCUSDT")



app = ApplicationBuilder().token(TOKEN).build()



app.add_handler(CommandHandler("start", start))

app.add_handler(CommandHandler("analyze", analyze))



app.run_polling()



from flask import Flask, request
import requests
import os
from datetime import datetime
import json
import threading
import time

# Importar funciones de Google Sheets
from google_sheets import registrar_entrada, registrar_salida, conectar_hoja

app = Flask(__name__)

# -------------------------------------------------------------------
# 1. CONFIGURACIONES ESENCIALES
# -------------------------------------------------------------------
BOT_TOKEN_DELTA  = "7876669003:AAEDoCKopyQY8d3-hjj4L_vdR3-TdNi_TMc"
TELEGRAM_KEY     = "Bossio.18357009"  # para el payload a WordPress

# [ESPAÑOL] IDs de grupo y canal
GROUP_CHAT_ID_ES   = "-1002299713092"  # Grupo en español
CHANNEL_CHAT_ID_ES = "-1002440626725"  # Canal en español

# Tópicos/hilos en el grupo ES
TOPICS_ES = {
    "BTC": 4,
    "ETH": 11,
    "ADA": 2,
    "XRP": 9,
    "BNB": 7
}

# [INGLÉS] IDs de grupo y canal
GROUP_CHAT_ID_EN   = "-1002428632182"  # Grupo en inglés
CHANNEL_CHAT_ID_EN = "-1002288256984"  # Canal en inglés

# Tópicos/hilos en el grupo EN
TOPICS_EN = {
    "BTC": 6,
    "ETH": 8,
    "ADA": 14,
    "XRP": 10,
    "BNB": 12
}

# Endpoints de WordPress
WORDPRESS_ENDPOINT     = "https://cryptosignalbot.com/wp-json/dashboard/v1/recibir-senales-swing"
WORDPRESS_ENDPOINT_ALT = "https://cryptosignalbot.com/wp-json/dashboard/v1/ver-historial-swing"

APALANCAMIENTO = 10

# -------------------------------------------------------------------
# 2. RUTA PRINCIPAL
# -------------------------------------------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    print(f"[DEBUG] Datos recibidos: {data}")
    return process_signal(data)

# -------------------------------------------------------------------
# 3. LÓGICA PRINCIPAL
# -------------------------------------------------------------------
def process_signal(data):
    ticker    = data.get('ticker', '').upper()
    action    = data.get('order_action', '').lower()  # buy / sell / close

    # Aceptar tanto coma como punto decimal
    raw_price   = data.get('order_price', "")
    order_price = str(raw_price).replace(',', '.')

    if not order_price:
        return "Precio no proporcionado", 400

    # Identificar tópico
    asset_es, topic_es = identificar_activo_es(ticker)
    asset_en, topic_en = identificar_activo_en(ticker)
    if not asset_es:
        return "Activo no reconocido", 400

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    # ------- BUY -------
    if action == "buy":
        registrar_entrada(ticker, float(order_price))

        # stop al 20%
        stop_loss    = round(float(order_price) * 0.80, 4)
        msg_buy_es   = construir_mensaje_compra_es(asset_es, order_price, stop_loss, fecha_hoy)
        msg_buy_en   = build_buy_message_en(asset_en, order_price, stop_loss, fecha_hoy)

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES, topic_es, msg_buy_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN, topic_en, msg_buy_en)

        payload = {
            "telegram_key": TELEGRAM_KEY,
            "symbol": asset_es,
            "action": action,
            "price": order_price,
            "stop_loss": stop_loss,
            "strategy": "fire_scalping"
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT, payload)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload)
        return "OK", 200

    # ------- SELL/CLOSE -------
    if action in ("sell", "close"):
        # 1) Recuperar de Sheets la última entrada abierta
        sheet   = conectar_hoja()
        records = sheet.get_all_records(value_render_option='UNFORMATTED_VALUE')

        entry_price = None
        entry_date  = None
        for row in reversed(records):
            if row["activo"] == ticker and row["precio_salida"] == "":
                entry_price = float(str(row["precio_entrada"]).replace(',', '.'))
                entry_date  = row["fecha_hora_entrada"]
                break
        if entry_price is None:
            return "No hay posición abierta para cerrar", 400

        # 2) Registrar la salida
        registrar_salida(ticker, float(order_price))

        exit_price      = float(order_price)
        profit_pct      = (exit_price - entry_price) / entry_price * 100
        profit_leverage = profit_pct * APALANCAMIENTO

        msg_close_es = construir_mensaje_cierre_es(
            asset_es, entry_price, exit_price, profit_leverage, entry_date, fecha_hoy
        )
        msg_close_en = build_close_message_en(
            asset_en, entry_price, exit_price, profit_leverage, entry_date, fecha_hoy
        )

        send_telegram_group_message_with_button_es(GROUP_CHAT_ID_ES, topic_es, msg_close_es)
        send_telegram_group_message_with_button_en(GROUP_CHAT_ID_EN, topic_en, msg_close_en)

        if profit_leverage >= 0:
            channel_es = construir_mensaje_ganancia_canal_es(
                asset_es, entry_price, exit_price, profit_leverage, entry_date, fecha_hoy
            )
            channel_en = build_profit_channel_msg_en(
                asset_en, entry_price, exit_price, profit_leverage, entry_date, fecha_hoy
            )
            send_telegram_channel_message_with_button_es(CHANNEL_CHAT_ID_ES, channel_es)
            send_telegram_channel_message_with_button_en(CHANNEL_CHAT_ID_EN, channel_en)

        # 3) Payload de cierre
        payload = {
            "telegram_key": TELEGRAM_KEY,
            "symbol": asset_es,
            "action": action,
            "entry_price": entry_price,
            "stop_loss": round(entry_price * 0.80, 4),
            "price": order_price,
            "strategy": "fire_scalping",
            "result": round(profit_leverage, 2)
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT, payload)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload)
        return "OK", 200

    return "OK", 200

# -------------------------------------------------------------------
# 4. KEEP-ALIVE para Render (ping cada 5m)
# -------------------------------------------------------------------
def _keep_alive():
    url = os.getenv("KEEPALIVE_URL", "https://delta-f42n.onrender.com/ping")
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"[KEEPALIVE] {r.status_code} → {url}")
        except Exception as e:
            print(f"[KEEPALIVE] Error: {e}")
        time.sleep(300)

# -------------------------------------------------------------------
# 5. FUNCIONES MENSAJES (ESPAÑOL)
# -------------------------------------------------------------------
def construir_mensaje_compra_es(asset, order_price, stop_loss, fecha_hoy):
    return (
        f"🟢 **ABRIR LONG | ZONA CONFIRMADA**\n\n"
        f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
        f"📈 **Operacion: Long**\n"
        f"💰 **Activo:** {asset}/USDT\n"
        f"✅ **Entrada:** {order_price} USDT\n"
        f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
        f"⛔ **Stop Loss:** {stop_loss} USDT\n"
        f"📅 **Fecha:** {fecha_hoy}\n"
        f"🎯 **Take Profit:** **Señal generada en tiempo real**\n\n"
        f"🎯 **El Take Profit se activa cuando se detecta un punto óptimo de salida.** "
        f"Nuestro equipo de analistas monitorea el mercado en **tiempo real**, aplicando análisis técnico "
        f"y fundamental para identificar las mejores oportunidades. Recibirás un mensaje con los detalles "
        f"cuando la operación deba ser cerrada.\n\n"
        f"⏳ **Estado:** EN CURSO, esperando señal de cierre...\n\n"
    )

def construir_mensaje_cierre_es(asset, precio_entrada, precio_salida,
                                profit_leveraged, fecha_entrada, fecha_cierre):
    if profit_leveraged >= 0:
        resultado_str = f"🟢 +{profit_leveraged:.2f}%"
        return (
            f"🎯 **TARGET ALCANZADO | CERRAR TOMAR GANANCIAS**\n\n"
            f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – Operación Cerrada**\n"
            f"¡Felicidades! Hemos cerrado la operación con beneficios.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )
    else:
        resultado_str = f"🔴 {profit_leveraged:.2f}%"
        return (
            f"🛑 **🔻 STOP LOSS ACTIVADO | CERRAR EN PÉRDIDA**\n\n"
            f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – Gestión de Riesgo**\n"
            f"El mercado tomó una dirección inesperada, pero aplicamos nuestra gestión "
            f"de riesgo para minimizar pérdidas.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )

def construir_mensaje_ganancia_canal_es(asset, precio_entrada, precio_salida,
                                        profit_leveraged, fecha_entrada, fecha_cierre):
    return (
        f"🚀 **TARGET ALCANZADO | ¡Otra operación cerrada con éxito! 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n\n"
        f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
        f"💰 **Activo:** {asset}/USDT\n"
        f"✅ **Entrada:** {precio_entrada} USDT\n"
        f"🔒 **Cierre:** {precio_salida} USDT\n"
        f"📊 **Resultado:** 🟢 +{profit_leveraged:.2f}%\n\n"
        f"📡 **Estrategia 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
        f"Nuestro sistema Delta Swing detectó el momento óptimo para cerrar la operación y asegurar "
        f"**beneficios en esta oportunidad de mercado**. Si quieres recibir nuestras señales VIP de "
        f"la estrategia 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 en **tiempo real**, suscríbete y accede a Señales, "
        f"**gráficos en vivo, rendimiento detallado y la lista de operaciones cerradas**.\n\n"
        f"🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – Prueba Gratuita por 30 Días🎉\n"
        f"📊 Señales, gráficos en vivo y análisis en tiempo real completamente GRATIS por 30 días.\n\n"
        f"🔑 ¡Obten tu Prueba Gratuita! 🚀\n"
    )

# -------------------------------------------------------------------
# 6. FUNCIONES MENSAJES (INGLÉS)
# -------------------------------------------------------------------
def build_buy_message_en(asset, order_price, stop_loss, fecha_hoy):
    return (
        f"🟢 **OPEN LONG | ZONE CONFIRMED**\n\n"
        f"🚨 **Strategy: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
        f"📈 **Operation: Long**\n"
        f"💰 **Asset:** {asset}/USDT\n"
        f"✅ **Price:** {order_price} USDT\n"
        f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
        f"⛔ **Stop Loss:** {stop_loss} USDT\n"
        f"📅 **Date:** {fecha_hoy}\n"
        f"🎯 **Take Profit:** **Real-time generated signal**\n\n"
        f"🎯 **The Take Profit is triggered when an optimal exit point is detected.** Our team of analysts "
        f"monitors the market in **real-time**, applying technical and fundamental analysis to identify "
        f"the best opportunities. You will receive a message with all the details when the trade needs to be closed.\n\n"
        f"⏳ **Status:** IN PROGRESS, waiting for a closing signal...\n\n"
    )

def build_close_message_en(asset, entry_price, exit_price,
                           profit_leveraged, entry_date, close_date):
    if profit_leveraged >= 0:
        result_str = f"🟢 +{profit_leveraged:.2f}%"
        msg = (
            f"🎯 **TARGET REACHED | CLOSE TO TAKE PROFITS**\n\n"
            f"🚨 **Strategy: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operation: Long**\n"
            f"💰 **Asset:** {asset}/USDT\n"
            f"✅ **Entry:** {entry_price} USDT\n"
            f"🔒 **Exit:** {exit_price} USDT\n"
            f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
            f"📅 **Opened:** {entry_date}\n"
            f"📅 **Closed:** {close_date}\n"
            f"📊 **Result:** {result_str}\n\n"
            f"📡 **🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 Strategy – Trade Closed**\n"
            f"Congratulations! We have successfully closed the trade with profits.\n\n"
            f"⏳ **Status:** Trade finalized."
        )
    else:
        result_str = f"🔴 {profit_leveraged:.2f}%"
        msg = (
            f"🛑 **🔻 STOP LOSS TRIGGERED | CLOSE AT A LOSS**\n\n"
            f"🚨 **Strategy: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operation: Long**\n"
            f"💰 **Asset:** {asset}/USDT\n"
            f"✅ **Entry:** {entry_price} USDT\n"
            f"🔒 **Exit:** {exit_price} USDT\n"
            f"⚖️ **Leverage:** {APALANCAMIENTO}x\n"
            f"📅 **Opened:** {entry_date}\n"
            f"📅 **Closed:** {close_date}\n"
            f"📊 **Result:** {result_str}\n\n"
            f"📡 **🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 Strategy – Risk Management**\n"
            f"The market took an unexpected turn, but we applied our risk management strategy to minimize losses.\n\n"
            f"⏳ **Status:** Trade finalized."
        )

def build_profit_channel_msg_en(asset, entry_price, exit_price,
                                profit_leveraged, entry_date, close_date):
    return (
		f"🚀 **TARGET HIT | Another successful trade closed! 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n\n"
		f"🚨 **Strategy: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
		f"💰 **Asset:** {asset}/USDT\n"
		f"✅ **Entry:** {entry_price} USDT\n"
		f"📉 **Exit:** {exit_price} USDT\n"
		f"🔒 **Leverage:** {APALANCAMIENTO}x\n"
		f"📅 **Opened:** {entry_date}\n"
		f"📅 **Closed:** {close_date}\n"
		f"📊 **Result:** 🟢 +{profit_leveraged:.2f}%\n\n"
		f"📡 We work hard analyzing 5 high-volume cryptocurrencies: "
		f"Bitcoin (BTC), ETH, BNB, ADA, and XRP.\n"
		f"Our system runs on a robust platform with our own website, "
		f"automated interface, real-time signals and 24/7 support.\n\n"
		f"💎 We show verified results, "
		f"all of our signals include a full 1-year trade history "
		f"and are backed by real stats and public verification on the website.\n\n"
		f"---\n"
		f"🎁 Join our Premium Zone and access VIP signals with real and verified results.\n"
		f"📌 *The data shown is from Bitcoin (1-year full history), but applying this strategy across 5 cryptocurrencies, results can be up to 5x greater.*\n\n"
		f"• Real-time signals sent to our website and Telegram\n"
		f"• Public trade history (12 full months)\n"
		f"• Live charting platform with multi-timeframe analysis\n"
		f"• Economic calendar and daily market news\n"
		f"• 24/7 support for any questions or setup help\n\n"
		f"---\n"
		f"🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – FREE 🎉\n"
		f"📊 Real-time signals, live charts and full market analysis completely FREE for 7 days.\n\n"
		f"🔑 Claim your FREE for 7 days now! 🚀\n"
	)

# -------------------------------------------------------------------
# 7. FUNCIONES DE ENVÍO A TELEGRAM
# -------------------------------------------------------------------
def send_telegram_group_message_with_button_es(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_FIRE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"📊 Ver gráficos en vivo","url":"https://cryptosignalbot.com/swing-trading-crypto-signal-bot-delta-swing/"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_channel_message_with_button_es(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_FIRE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"🎁 Señales VIP","url":"https://t.me/CriptoSignalBotGestion_bot"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_group_message_with_button_en(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_FIRE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"📊 View live charts","url":"https://cryptosignalbot.com/swing-trading-crypto-signal-bot-delta-swing/"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'message_thread_id': thread_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

def send_telegram_channel_message_with_button_en(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_FIRE}/sendMessage"
    botones = {
        "inline_keyboard": [
            [{"text":"🎁 VIP Signals","url":"https://t.me/CriptoSignalBotGestion_bot"}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': botones
    }
    requests.post(url, json=payload)

# -------------------------------------------------------------------
# 8. UTILIDADES
# -------------------------------------------------------------------
def enviar_a_wordpress(endpoint, payload):
    try:
        requests.post(endpoint, json=payload)
    except:
        pass

def identificar_activo_es(ticker):
    t = ticker.upper()
    if "BTC" in t: return ("BTC", TOPICS_ES["BTC"])
    if "ETH" in t: return ("ETH", TOPICS_ES["ETH"])
    if "ADA" in t: return ("ADA", TOPICS_ES["ADA"])
    if "XRP" in t: return ("XRP", TOPICS_ES["XRP"])
    if "BNB" in t: return ("BNB", TOPICS_ES["BNB"])
    return (None, None)

def identificar_activo_en(ticker):
    t = ticker.upper()
    if "BTC" in t: return ("BTC", TOPICS_EN["BTC"])
    if "ETH" in t: return ("ETH", TOPICS_EN["ETH"])
    if "ADA" in t: return ("ADA", TOPICS_EN["ADA"])
    if "XRP" in t: return ("XRP", TOPICS_EN["XRP"])
    if "BNB" in t: return ("BNB", TOPICS_EN["BNB"])
    return (None, None)

# -------------------------------------------------------------------
# 9. ARRANQUE
# -------------------------------------------------------------------
@app.route('/ping', methods=['GET'])
def ping():
    return 'pong', 200

if __name__ == '__main__':
    threading.Thread(target=_keep_alive, daemon=True).start()
    port = int(os.environ.get("PORT", 1000))
    app.run(host='0.0.0.0', port=port)

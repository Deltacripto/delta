from flask import Flask, request
import requests
import os
from datetime import datetime
import json

app = Flask(__name__)

# ------------------------------------------------------------------------------
# 1. CONFIGURACIONES ESENCIALES
# ------------------------------------------------------------------------------
BOT_TOKEN_DELTA      = "7876669003:AAEDoCKopyQY8d3-hjj4L_vdR3-TdNi_TMc"

# [ESPAÑOL] IDs de grupo y canal (canal ya no se usa)
GROUP_CHAT_ID_ES     = "-1002299713092"      # Grupo en español

# Tópicos/hilos en el grupo ES
TOPICS_ES = {
    "BTC": 4,
    "ETH": 11,
    "ADA": 2,
    "XRP": 9,
    "BNB": 7
}

# [INGLÉS] IDs de grupo (canal ya no se usa)
GROUP_CHAT_ID_EN     = "-1002428632182"      # Grupo en inglés

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

# Clave secreta
TELEGRAM_KEY          = "Bossio.18357009"

# Archivo para guardar el estado de las operaciones
datos_guardados_file  = "estado_operaciones.json"

# Cargar datos si existen
if os.path.exists(datos_guardados_file):
    with open(datos_guardados_file, "r") as f:
        try:
            data_json       = json.load(f)
            precios_entrada = data_json.get("precios_entrada", {})
            fechas_entrada  = data_json.get("fechas_entrada", {})
        except json.JSONDecodeError:
            precios_entrada = {}
            fechas_entrada  = {}
else:
    precios_entrada = {}
    fechas_entrada  = {}

# Función para guardar datos persistentes
def guardar_estado():
    with open(datos_guardados_file, "w") as f:
        json.dump({
            "precios_entrada": precios_entrada,
            "fechas_entrada": fechas_entrada
        }, f)

# Apalancamiento
APALANCAMIENTO = 3

# ------------------------------------------------------------------------------
# 2. RUTA PRINCIPAL DEL SERVIDOR FLASK
# ------------------------------------------------------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"[DEBUG] Datos recibidos: {data}")
    return process_signal(data)

# ------------------------------------------------------------------------------
# 3. LÓGICA PRINCIPAL
# ------------------------------------------------------------------------------
def process_signal(data):
    global precios_entrada, fechas_entrada

    ticker      = data.get('ticker', 'No especificado')
    action      = data.get('order_action', '').lower()  # "buy", "sell", "close"
    order_price = data.get('order_price', None)
    _           = data.get('stop_loss', None)  # ignorado

    if not order_price:
        return "Precio no proporcionado", 400

    asset_es, topic_id_es = identificar_activo_es(ticker)
    asset_en, topic_id_en = identificar_activo_en(ticker)

    if not asset_es or not asset_en:
        return "Activo no reconocido", 400

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    # --------------------------------------------------------------------------
    # A) LÓGICA PARA BUY
    # --------------------------------------------------------------------------
    if action == "buy":
        # --- Eliminada la verificación de operación previa ---
        # Se calcula el Stop Loss al 20% por debajo del precio de entrada
        stop_loss_value              = round(float(order_price) * 0.80, 4)
        precios_entrada[asset_es]    = float(order_price)
        fechas_entrada[asset_es]     = fecha_hoy
        guardar_estado()

        mensaje_compra_es = construir_mensaje_compra_es(
            asset_es, order_price, stop_loss_value, fecha_hoy
        )
        mensaje_compra_en = build_buy_message_en(
            asset_en, order_price, stop_loss_value, fecha_hoy
        )

        # Envío solo a grupo ES
        send_telegram_group_message_with_button_es(
            GROUP_CHAT_ID_ES, topic_id_es, mensaje_compra_es
        )
        # Envío solo a grupo EN
        send_telegram_group_message_with_button_en(
            GROUP_CHAT_ID_EN, topic_id_en, mensaje_compra_en
        )

        payload_wp = {
            "telegram_key": TELEGRAM_KEY,
            "symbol":       asset_es,
            "action":       action,
            "price":        order_price,
            "stop_loss":    stop_loss_value,
            "strategy":     "fire_scalping"
        }
        enviar_a_wordpress(WORDPRESS_ENDPOINT,     payload_wp)
        enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload_wp)

        return "OK", 200

    # --------------------------------------------------------------------------
    # B) LÓGICA PARA SELL / CLOSE
    # --------------------------------------------------------------------------
    if action in ["sell", "close"]:
        if asset_es in precios_entrada and precios_entrada[asset_es] is not None:
            precio_entrada    = precios_entrada[asset_es]
            precio_salida     = float(order_price)
            fecha_entrada_op  = fechas_entrada.get(asset_es, "Desconocida")
            guardar_estado()

            profit_percent            = ((precio_salida - precio_entrada) / precio_entrada) * 100
            profit_percent_leveraged  = profit_percent * APALANCAMIENTO

            mensaje_cierre_es = construir_mensaje_cierre_es(
                asset_es, precio_entrada, precio_salida,
                profit_percent_leveraged, fecha_entrada_op, fecha_hoy
            )
            mensaje_cierre_en = build_close_message_en(
                asset_en, precio_entrada, precio_salida,
                profit_percent_leveraged, fecha_entrada_op, fecha_hoy
            )

            # Enviar solo a grupo ES
            send_telegram_group_message_with_button_es(
                GROUP_CHAT_ID_ES, topic_id_es, mensaje_cierre_es
            )
            # --- Eliminadas las llamadas al canal ---
            # send_telegram_channel_message_with_button_es(...)
            # send_telegram_channel_message_with_button_en(...)

            # Enviar solo a grupo EN
            send_telegram_group_message_with_button_en(
                GROUP_CHAT_ID_EN, topic_id_en, mensaje_cierre_en
            )

            precios_entrada[asset_es] = None
            fechas_entrada[asset_es]  = None

            wp_result = round(profit_percent_leveraged, 2)
            payload_wp = {
                "telegram_key": TELEGRAM_KEY,
                "symbol":       asset_es,
                "action":       action,
                "price":        order_price,
                "strategy":     "fire_scalping",
                "result":       wp_result
            }
            enviar_a_wordpress(WORDPRESS_ENDPOINT,     payload_wp)
            enviar_a_wordpress(WORDPRESS_ENDPOINT_ALT, payload_wp)

            return "OK", 200
        else:
            return "No hay posición abierta para cerrar", 400

    return "OK", 200

# ------------------------------------------------------------------------------
# 4. FUNCIONES MENSAJES (ESPAÑOL)
# ------------------------------------------------------------------------------
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
        f"Nuestro equipo de analistas monitorea el mercado en **tiempo real**, aplicando "
        f"análisis técnico y fundamental para identificar las mejores oportunidades. "
        f"Recibirás un mensaje con todos los detalles cuando la operación deba ser cerrada.\n\n"
        f"⏳ **Estado:** EN CURSO, esperando señal de cierre...\n\n"
    )

def construir_mensaje_cierre_es(asset, precio_entrada, precio_salida,
                                profit_leveraged, fecha_entrada, fecha_cierre):
    if profit_leveraged >= 0:
        resultado_str = f"🟢 +{profit_leveraged:.2f}%"
        msg = (
            f"🎯 **TARGET ALCANZADO | CERRAR TOMAR GANANCIAS**\n\n"
            f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
            f"📅 **Apertura:** {fecha_entrada}\n"
            f"📅 **Cierre:** {fecha_cierre}\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – Operación Cerrada**\n"
            f"¡Felicidades! Hemos cerrado la operación con beneficios.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )
    else:
        resultado_str = f"🔴 {profit_leveraged:.2f}%"
        msg = (
            f"🛑 **🔻 STOP LOSS ACTIVADO | CERRAR EN PÉRDIDA**\n\n"
            f"🚨 **Estrategia: 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠**\n"
            f"📈 **Operacion: Long**\n"
            f"💰 **Activo:** {asset}/USDT\n"
            f"✅ **Entrada:** {precio_entrada} USDT\n"
            f"🔒 **Cierre:** {precio_salida} USDT\n"
            f"⚖️ **Apalancamiento:** {APALANCAMIENTO}x\n"
            f"📅 **Apertura:** {fecha_entrada}\n"
            f"📅 **Cierre:** {fecha_cierre}\n"
            f"📊 **Resultado:** {resultado_str}\n\n"
            f"📡 **Estrategia 🪙 𝐃𝐄𝐋𝐓𝐀 𝐒𝐰𝐢𝐧𝐠 – Gestión de Riesgo**\n"
            f"El mercado tomó una dirección inesperada, pero aplicamos nuestra gestión "
            f"de riesgo para minimizar pérdidas.\n\n"
            f"⏳ **Estado:** Operación finalizada."
        )
    return msg

# ------------------------------------------------------------------------------
# 5. FUNCIONES MENSAJES (INGLÉS)
# ------------------------------------------------------------------------------
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
    return msg

# ------------------------------------------------------------------------------
# 6. FUNCIONES DE ENVÍO A TELEGRAM (solo grupos)
# ------------------------------------------------------------------------------
def send_telegram_group_message_with_button_es(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_DELTA}/sendMessage"
    botones = {
        "inline_keyboard": [[
            {"text": "📊 Ver gráficos, señales en vivo",
             "url": "https://cryptosignalbot.com/swing-trading-crypto-signal-bot-delta-swing/"}
        ]]
    }
    payload = {
        'chat_id':           chat_id,
        'message_thread_id': thread_id,
        'text':              text,
        'parse_mode':        'Markdown',
        'reply_markup':      botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][ES] Grupo: {resp.json()}")

def send_telegram_group_message_with_button_en(chat_id, thread_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN_DELTA}/sendMessage"
    botones = {
        "inline_keyboard": [[
            {"text": "📊 View charts & live signals",
             "url": "https://cryptosignalbot.com/swing-trading-crypto-signal-bot-delta-swing/"}
        ]]
    }
    payload = {
        'chat_id':           chat_id,
        'message_thread_id': thread_id,
        'text':              text,
        'parse_mode':        'Markdown',
        'reply_markup':      botones
    }
    resp = requests.post(url, json=payload)
    print(f"[DEBUG][EN] Group: {resp.json()}")

# ------------------------------------------------------------------------------
# 7. UTILIDADES
# ------------------------------------------------------------------------------
def enviar_a_wordpress(endpoint, payload):
    try:
        resp = requests.post(endpoint, json=payload)
        print(f"[DEBUG] WP resp ({endpoint}): {resp.text}")
    except Exception as e:
        print(f"[ERROR] Enviando a WordPress: {e}")

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

# ------------------------------------------------------------------------------
# 8. EJECUCIÓN DEL SERVIDOR FLASK
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

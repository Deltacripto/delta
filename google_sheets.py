import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials

SCOPE       = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE  = os.getenv("GOOGLE_CREDS_FILENAME", "credenciales_google.json")
SHEET_NAME  = os.getenv("GOOGLE_SHEETS_NAME", "EstadoOperaciones")

def conectar_hoja():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    return sheet

def cargar_estado_desde_google():
    sheet = conectar_hoja()
    data = sheet.get_all_records()
    precios_entrada, fechas_entrada = {}, {}
    for row in data:
        precios_entrada[row['asset']] = float(row['entry_price']) if row['entry_price'] else None
        fechas_entrada[row['asset']]  = row['entry_date'] if row['entry_date'] else None
    return precios_entrada, fechas_entrada

def guardar_estado_en_google(precios_entrada, fechas_entrada):
    sheet = conectar_hoja()
    sheet.clear()
    sheet.append_row(['asset', 'entry_price', 'entry_date'])
    for asset in precios_entrada:
        precio = precios_entrada.get(asset, '')
        fecha  = fechas_entrada.get(asset, '')
        sheet.append_row([asset, precio, fecha])

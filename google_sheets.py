# google_sheets.py – acceso a Google Sheets con:
# • Variable GOOGLE_CREDS_JSON (JSON completo)          ← recomendado
# • o archivo credenciales_google.json en disco
# Si falta cualquiera de las dos, lanza un error claro.

import os
import tempfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ---------------- Config desde entorno -----------------
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

CREDS_FILE  = os.getenv("GOOGLE_CREDS_FILENAME", "credenciales_google.json")
CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")          # JSON completo (secreto)
SHEET_NAME  = os.getenv("GOOGLE_SHEETS_NAME", "EstadoOperaciones")

# -------------- Credenciales: elegir fuente -------------
def _ensure_creds_file() -> str:
    """
    • Si GOOGLE_CREDS_JSON existe, lo guarda en un archivo temporal
      y devuelve esa ruta.
    • Si no, usa CREDS_FILE si está presente en disco.
    • Si ninguno existe, detiene la app con mensaje claro.
    """
    # Caso A: JSON en variable de entorno
    if CREDS_JSON:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(CREDS_JSON.encode())
        tmp.close()
        return tmp.name

    # Caso B: archivo físico en la imagen
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE

    # Ninguna fuente disponible → error descriptivo
    raise FileNotFoundError(
        "❌ No se encontraron credenciales de Google Sheets.\n"
        "• Sube credenciales_google.json al contenedor, o\n"
        "• Crea la variable de entorno GOOGLE_CREDS_JSON con el JSON completo."
    )

CREDS_PATH = _ensure_creds_file()

# -------------- Conexión y helpers ----------------------
def conectar_hoja():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def cargar_estado_desde_google():
    hoja = conectar_hoja()
    data = hoja.get_all_records()
    precios, fechas = {}, {}
    for row in data:
        precios[row["asset"]] = float(row["entry_price"]) if row["entry_price"] else None
        fechas[row["asset"]]  = row["entry_date"]         if row["entry_date"]  else None
    return precios, fechas

def guardar_estado_en_google(precios, fechas):
    hoja = conectar_hoja()
    hoja.clear()
    hoja.append_row(["asset", "entry_price", "entry_date"])
    for asset in precios:
        hoja.append_row([
            asset,
            precios.get(asset, ""),
            fechas.get(asset, ""),
        ])

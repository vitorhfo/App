import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(BASE_DIR)
if os.path.basename(APP_ROOT).lower() == "arquivos_raw":
    APP_ROOT = os.path.dirname(APP_ROOT)

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.environ.get("ORCAMENTO_DB_PATH", os.path.join(DATA_DIR, "orcamento.db"))
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

RAW_DIR = os.path.join(APP_ROOT, "arquivos_raw")
DADOS_DIR = os.path.join(APP_ROOT, "DADOS")

HOST = "127.0.0.1"
PORT = 8080

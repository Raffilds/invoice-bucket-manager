import pandas as pd
from google.cloud import storage
from urllib.parse import urlparse
from datetime import datetime
import os

# =========================
# CONFIG
# =========================
BUCKET = "tim-faturas"
ARQUIVO_EXCEL = "faturas_registradas.xlsx"

# MODOS:
# "simulacao" → só log (não copia nem deleta)
# "backup" → faz backup apenas
# "producao" → backup + delete
MODO = "backup"

TIPOS = ["BT", "GD"]

# =========================
# CLIENT
# =========================
client = storage.Client()
bucket = client.bucket(BUCKET)

# =========================
# DATA / LOG / BACKUP
# =========================
agora = datetime.now()
data_str = agora.strftime("%Y-%m-%d")
hora_str = agora.strftime("%H-%M-%S")

# ✅ PASTA DE LOG
LOG_DIR = f"docs/logs/{data_str}"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"log_execucao_{hora_str}.txt")

# ✅ PREFIXO DE BACKUP
BACKUP_PREFIX = f"backup/{data_str}"


def log(msg):
    linha = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linha)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def montar_caminhos(link):
    path = urlparse(link).path
    partes = path.strip("/").split("/")

    uc = partes[1]
    empresa = partes[2]
    fatura = partes[3]

    nome = f"{empresa}_{uc}_{fatura}.pdf"

    return [
        f"{tipo}/{empresa}/{uc}/{nome}"
        for tipo in TIPOS
    ]


# =========================
# INÍCIO
# =========================
log("🚀 Início da execução")
log(f"🔧 MODO EXECUÇÃO: {MODO}")

# =========================
# LER EXCEL
# =========================
df = pd.read_excel(ARQUIVO_EXCEL)
df.columns = df.columns.str.strip().str.lower()

if "link" not in df.columns:
    raise Exception(f"Coluna 'link' não encontrada. Colunas disponíveis: {df.columns}")

links = df["link"].dropna().tolist()

log(f"📄 Total de links: {len(links)}")

# =========================
# BUSCA
# =========================
arquivos_encontrados = []

log("🔎 Iniciando busca...")

for link in links:
    caminhos = montar_caminhos(link)
    encontrado = False

    for caminho in caminhos:
        blob = bucket.blob(caminho)

        if blob.exists():
            log(f"✅ ENCONTRADO: {caminho}")
            arquivos_encontrados.append(caminho)
            encontrado = True
            break

    if not encontrado:
        log(f"❌ NAO_ENCONTRADO: {link}")

log(f"📊 Total encontrados: {len(arquivos_encontrados)}")

# =========================
# CONFIRMAÇÃO
# =========================
if arquivos_encontrados:

    confirm = input("\nDigite 'excluir itens' para continuar: ")

    if confirm.strip().lower() != "excluir itens":
        log("❌ Operação cancelada pelo usuário")
        exit()

    # 🔐 confirmação extra para produção
    if MODO == "producao":
        confirm2 = input("⚠️ Confirme digitando 'confirmar producao': ")
        if confirm2 != "confirmar producao":
            log("❌ Execução abortada por segurança")
            exit()

    log("⚙️ Processando arquivos...")

    for caminho in arquivos_encontrados:
        try:
            blob_origem = bucket.blob(caminho)
            destino_backup = f"{BACKUP_PREFIX}/{caminho}"

            if MODO == "simulacao":

                log(f"[SIMULAÇÃO] BACKUP -> {destino_backup}")
                log(f"[SIMULAÇÃO] DELETE -> {caminho}")

            elif MODO == "backup":

                # ✅ BACKUP REAL
                bucket.copy_blob(blob_origem, bucket, destino_backup)
                log(f"✅ BACKUP OK: {destino_backup}")

                log(f"⚠️ DELETE NÃO EXECUTADO (modo backup)")

            elif MODO == "producao":

                # ✅ BACKUP
                bucket.copy_blob(blob_origem, bucket, destino_backup)
                log(f"✅ BACKUP OK: {destino_backup}")

                # ✅ DELETE
                blob_origem.delete()
                log(f"🗑️ DELETADO: {caminho}")

            else:
                log(f"❌ MODO inválido: {MODO}")
                break

        except Exception as e:
            log(f"❌ ERRO: {caminho} -> {e}")

    log("✅ Processo concluído")

else:
    log("❌ Nenhum arquivo encontrado")

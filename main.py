import pandas as pd
from google.cloud import storage
from urllib.parse import urlparse
from datetime import datetime
import argparse
import yaml
import os

# =========================
# CLI
# =========================
parser = argparse.ArgumentParser()

parser.add_argument("--mode", choices=["simulacao", "backup", "producao", "rollback"], default="simulacao")
parser.add_argument("--input", help="Arquivo Excel")
parser.add_argument("--data-backup", help="Data para rollback YYYY-MM-DD")

args = parser.parse_args()

# =========================
# LOAD CONFIG
# =========================
with open("config.yaml") as f:
    config = yaml.safe_load(f)

BUCKET_NAME = config["bucket"]
TIPOS = config["tipos"]

LOG_BASE = config["paths"]["logs"]
REPORT_BASE = config["paths"]["reports"]
BACKUP_BASE = config["paths"]["backup_prefix"]

ARQUIVO_EXCEL = args.input if args.input else config["excel"]["file"]
COLUNA = config["excel"]["column"]

# =========================
# INIT
# =========================
client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

now = datetime.now()
data_str = now.strftime("%Y-%m-%d")
hora_str = now.strftime("%H-%M-%S")

# LOG
LOG_DIR = f"{LOG_BASE}/{data_str}"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_TXT = os.path.join(LOG_DIR, f"log_{hora_str}.txt")
LOG_XLSX = LOG_TXT.replace(".txt", ".xlsx")

# REPORT
os.makedirs(REPORT_BASE, exist_ok=True)

# LOG BUFFER
logs_excel = []

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    linha = f"[{timestamp}] {level} - {msg}"
    print(linha)

    with open(LOG_TXT, "a", encoding="utf-8") as f:
        f.write(linha + "\n")

    logs_excel.append({
        "timestamp": timestamp,
        "level": level,
        "message": msg
    })

# =========================
# FUNÇÃO PATH
# =========================
def montar_caminhos(link):
    partes = urlparse(link).path.strip("/").split("/")

    uc = partes[1]
    empresa = partes[2]
    fatura = partes[3]

    nome = f"{empresa}_{uc}_{fatura}.pdf"

    return [f"{t}/{empresa}/{uc}/{nome}" for t in TIPOS]

# =========================
# ROLLBACK
# =========================
if args.mode == "rollback":

    if not args.data_backup:
        raise Exception("Use --data-backup YYYY-MM-DD")

    prefix = f"{BACKUP_BASE}/{args.data_backup}/"

    log("🚨 MODO ROLLBACK")
    log(f"Origem: {prefix}")

    restaurados = 0

    for blob in bucket.list_blobs(prefix=prefix):
        origem = blob.name
        destino = origem.replace(prefix, "")

        try:
            bucket.copy_blob(blob, bucket, destino)
            log(f"✅ RESTAURADO: {destino}")
            restaurados += 1

        except Exception as e:
            log(f"❌ ERRO: {destino} -> {e}", "ERROR")

    log(f"Total restaurados: {restaurados}")

# =========================
# OUTROS MODOS
# =========================
else:

    df = pd.read_excel(ARQUIVO_EXCEL)
    df.columns = df.columns.str.strip().str.lower()

    if COLUNA not in df.columns:
        raise Exception(f"Coluna {COLUNA} não encontrada")

    links = df[COLUNA].dropna().tolist()

    log(f"📄 Total links: {len(links)}")

    resultados = []

    # =========================
    # BUSCA
    # =========================
    for link in links:
        caminhos = montar_caminhos(link)

        encontrado = False
        final = None

        for caminho in caminhos:
            if bucket.blob(caminho).exists():
                encontrado = True
                final = caminho
                break

        status = "ENCONTRADO" if encontrado else "NAO_ENCONTRADO"

        resultados.append({
            "link": link,
            "status": status,
            "caminho": final
        })

        log(f"{status}: {final if final else link}")

    # =========================
    # RELATÓRIO
    # =========================
    df_result = pd.DataFrame(resultados)

    csv_path = f"{REPORT_BASE}/relatorio_{hora_str}.csv"
    xlsx_path = f"{REPORT_BASE}/relatorio_{hora_str}.xlsx"

    df_result.to_csv(csv_path, index=False)
    df_result.to_excel(xlsx_path, index=False)

    log(f"📊 CSV: {csv_path}")
    log(f"📊 Excel: {xlsx_path}")

    # =========================
    # EXECUÇÃO (AGORA INCLUI SIMULAÇÃO)
    # =========================
    if args.mode in ["simulacao", "backup", "producao"]:

        total_encontrados = len([r for r in resultados if r["status"] == "ENCONTRADO"])

        log(f"🔥 Total a processar: {total_encontrados}")

        confirm = input("Digite 'excluir itens': ")
        if confirm.lower() != "excluir itens":
            log("❌ Cancelado")
            exit()

        if args.mode == "producao":
            confirm2 = input("Digite 'confirmar producao': ")
            if confirm2 != "confirmar producao":
                log("❌ Abortado")
                exit()

        # =========================
        # PROCESSAMENTO
        # =========================
        for r in resultados:
            if r["status"] != "ENCONTRADO":
                continue

            origem = r["caminho"]
            destino = f"{BACKUP_BASE}/{data_str}/{origem}"

            try:
                if args.mode == "simulacao":
                    log(f"[SIMULAÇÃO] BACKUP -> {destino}")
                    log(f"[SIMULAÇÃO] DELETE -> {origem}")

                elif args.mode in ["backup", "producao"]:
                    bucket.copy_blob(bucket.blob(origem), bucket, destino)
                    log(f"✅ BACKUP: {destino}")

                if args.mode == "producao":
                    bucket.blob(origem).delete()
                    log(f"🗑️ DELETADO: {origem}")

            except Exception as e:
                log(f"❌ ERRO: {origem} -> {e}", "ERROR")

# =========================
# SALVAR LOG EXCEL
# =========================
df_logs = pd.DataFrame(logs_excel)
df_logs.to_excel(LOG_XLSX, index=False)

print("\n✅ EXECUÇÃO FINALIZADA")
print(f"📄 Log TXT: {LOG_TXT}")
print(f"📊 Log Excel: {LOG_XLSX}")

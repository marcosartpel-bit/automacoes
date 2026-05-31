# AUTO IMPORTADOR DE ESTOQUE - Bompapel / Cioffi
# TOTALi -> Supabase  |  Versao 3.1
# As credenciais sao lidas do arquivo .env (nunca commitar o .env)

import os, re, sys, json, logging, urllib.request, urllib.error
from datetime import datetime, timezone

# Carrega .env se existir
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

ARQUIVO_ESTOQUE = os.environ.get("ARQUIVO_ESTOQUE", r"C:\Users\Marcos\Desktop\Estoque\MRP26EST - Projeto APP de Estoque.XLS")
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_importador.log")
handlers = [logging.StreamHandler(sys.stdout)]
try:
    handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
except (PermissionError, OSError):
    print("[AVISO] Log bloqueado por outra instancia.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%d/%m/%Y %H:%M:%S", handlers=handlers)
log = logging.getLogger(__name__)

def to_n(v):
    if isinstance(v, (int, float)):
        return 0.0 if v != v else float(v)
    if not v:
        return 0.0
    try:
        return float(str(v).strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0

def ler_arquivo_sylk(caminho):
    with open(caminho, "rb") as f:
        return f.read().decode("latin-1")

def parse_sylk(texto):
    linhas = texto.split("\r\n")
    if len(linhas) < 5:
        linhas = texto.split("\n")
    curr_row, curr_col = 1, 1
    rows = {}
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("F;"):
            m = re.search(r";Y(\d+)", ln)
            if m: curr_row = int(m.group(1))
            m = re.search(r";X(\d+)", ln)
            if m: curr_col = int(m.group(1))
            continue
        if ln.startswith("C;"):
            m = re.search(r";Y(\d+)", ln)
            if m: curr_row = int(m.group(1))
            m = re.search(r";X(\d+)", ln)
            if m: curr_col = int(m.group(1))
            m = re.search(r";K(.*)", ln)
            if m:
                val = m.group(1)
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if curr_row not in rows:
                    rows[curr_row] = {}
                rows[curr_row][curr_col] = val
    return rows

BASE_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"
HEADERS_BASE = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY, "Content-Type": "application/json"}
TAMANHO_LOTE = 500

def requisicao(metodo, endpoint, dados=None, params="", prefer=None):
    url = BASE_URL + endpoint + params
    hdrs = dict(HEADERS_BASE)
    if prefer:
        hdrs["Prefer"] = prefer
    body = json.dumps(dados).encode("utf-8") if dados is not None else None
    req = urllib.request.Request(url, data=body, method=metodo, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()

def apagar_todos_produtos():
    log.info("Limpando tabela...")
    status, resp = requisicao("DELETE", "/produtos", params="?id=gt.0")
    if status in (200, 204):
        log.info("Tabela limpa.")
        return True
    log.error(f"Erro ao limpar: HTTP {status}")
    return False

def inserir_lote(lote, num, total_lotes):
    status, resp = requisicao("POST", "/produtos", dados=lote, prefer="return=minimal")
    if status in (200, 201):
        return True
    log.error(f"Lote {num}/{total_lotes} falhou HTTP {status}")
    return False

def importar_para_supabase(produtos):
    total = len(produtos)
    n_lotes = (total + TAMANHO_LOTE - 1) // TAMANHO_LOTE
    enviados, erros = 0, 0
    log.info(f"Enviando {total} produtos em {n_lotes} lotes...")
    for i in range(0, total, TAMANHO_LOTE):
        lote = produtos[i : i + TAMANHO_LOTE]
        num = i // TAMANHO_LOTE + 1
        if inserir_lote(lote, num, n_lotes):
            enviados += len(lote)
            log.info(f"  Lote {num}/{n_lotes} OK ({enviados}/{total})")
        else:
            erros += len(lote)
    return enviados, erros

def processar_arquivo():
    log.info("=" * 60)
    log.info("INICIO DA IMPORTACAO (v3.1)")
    log.info(f"Arquivo: {ARQUIVO_ESTOQUE}")
    if not os.path.exists(ARQUIVO_ESTOQUE):
        log.error("Arquivo nao encontrado!"); return False
    log.info(f"Tamanho: {os.path.getsize(ARQUIVO_ESTOQUE)/1024:.0f} KB")
    try:
        rows = parse_sylk(texto)
        log.info(f"Linhas SYLK: {len(rows)}")
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        unicos = {}
        for rk in sorted(k for k in rows if k >= 3):
            r = rows[rk]
            codigo = str(r.get(3, "")).strip()
            filial = str(r.get(5, "")).strip().upper()
            nome = str(r.get(6, "")).strip()
            if not codigo or not filial or not nome:
                continue
            unicos[(codigo, filial)] = {
                "codigo_barras": str(r.get(2, "")).strip(),
                "codigo": codigo, "filial": filial, "nome": nome,
                "marca": str(r.get(7, "")).strip(),
                "tributacao": str(r.get(8, "")).strip(),
                "saldo_real": to_n(r.get(9, 0)),
                "custo_reposicao": to_n(r.get(10, 0)),
                "total_estoque": to_n(r.get(11, 0)),
                "grupo": str(r.get(12, "")).strip(),
                "subgrupo": str(r.get(13, "")).strip(),
                "tipo": str(r.get(14, "")).strip(),
                "item": str(r.get(15, "")).strip(),
                "updated_at": agora
            }
        produtos = list(unicos.values())
        log.info(f"Produtos unicos: {len(produtos)}")
        contagem = {}
        for p in produtos:
            contagem[p["filial"]] = contagem.get(p["filial"], 0) + 1
        for f, q in sorted(contagem.items()):
            log.info(f"  {f}: {q} produtos")
    except Exception as e:
        log.error(f"Erro: {e}"); return False
    if not apagar_todos_produtos():
        return False
    enviados, erros = importar_para_supabase(produtos)
    if erros == 0:
        log.info(f"CONCLUIDO {enviados} produtos importados!")
    else:
        log.warning(f"PARCIAL - {enviados} ok, {erros} erro.")
    log.info("=" * 60)
    return erros == 0


if __name__ == "__main__":
    processar_arquivo()

import csv
import io
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Dicionário padrão de categorização baseado em palavras-chave comuns de estabelecimentos brasileiros
DEFAULT_CATEGORY_RULES: List[Tuple[str, str]] = [
    # Alimentação
    ("ifood", "Alimentação"),
    ("rappi", "Alimentação"),
    ("ubereats", "Alimentação"),
    ("supermercado", "Alimentação"),
    ("mercado", "Alimentação"),
    ("carrefour", "Alimentação"),
    ("pao de acucar", "Alimentação"),
    ("extra", "Alimentação"),
    ("atacadao", "Alimentação"),
    ("assai", "Alimentação"),
    ("tenda atacado", "Alimentação"),
    ("dia brasil", "Alimentação"),
    ("padaria", "Alimentação"),
    ("panificadora", "Alimentação"),
    ("restaurante", "Alimentação"),
    ("lanchonete", "Alimentação"),
    ("bar ", "Alimentação"),
    ("churrascaria", "Alimentação"),
    ("pizzaria", "Alimentação"),
    ("mcdonald", "Alimentação"),
    ("burger king", "Alimentação"),
    ("bk brasil", "Alimentação"),
    ("subway", "Alimentação"),
    ("habibs", "Alimentação"),
    ("starbucks", "Alimentação"),
    ("outback", "Alimentação"),
    ("madero", "Alimentação"),
    ("hortifruti", "Alimentação"),
    ("acougue", "Alimentação"),
    ("sorveteria", "Alimentação"),
    ("cacau show", "Alimentação"),
    ("kopenhagen", "Alimentação"),

    # Transporte
    ("uber", "Transporte"),
    ("99app", "Transporte"),
    ("99 pop", "Transporte"),
    ("99 corrida", "Transporte"),
    ("cabify", "Transporte"),
    ("posto", "Transporte"),
    ("shell", "Transporte"),
    ("ipiranga", "Transporte"),
    ("br distribuidora", "Transporte"),
    ("auto posto", "Transporte"),
    ("abastece", "Transporte"),
    ("combustivel", "Transporte"),
    ("estacionamento", "Transporte"),
    ("sem parar", "Transporte"),
    ("conectcar", "Transporte"),
    ("veloe", "Transporte"),
    ("pedagio", "Transporte"),
    ("bilhete unico", "Transporte"),
    ("metro", "Transporte"),
    ("sptrans", "Transporte"),
    ("latam", "Transporte"),
    ("gol linhas", "Transporte"),
    ("azul linhas", "Transporte"),
    ("voegol", "Transporte"),
    ("buser", "Transporte"),
    ("clickbus", "Transporte"),
    ("oficina", "Transporte"),
    ("pneus", "Transporte"),

    # Moradia & Contas
    ("aluguel", "Moradia"),
    ("condominio", "Moradia"),
    ("enel", "Moradia"),
    ("sabesp", "Moradia"),
    ("cpfl", "Moradia"),
    ("eletropaulo", "Moradia"),
    ("luz", "Moradia"),
    ("agua", "Moradia"),
    ("gas", "Moradia"),
    ("comgas", "Moradia"),
    ("claro", "Moradia"),
    ("vivo", "Moradia"),
    ("tim", "Moradia"),
    ("oi fixo", "Moradia"),
    ("net servicos", "Moradia"),
    ("internet", "Moradia"),
    ("iptu", "Moradia"),
    ("leroy merlin", "Moradia"),
    ("tok&stok", "Moradia"),
    ("camicado", "Moradia"),
    ("etna", "Moradia"),
    ("mobly", "Moradia"),

    # Assinaturas & Lazer
    ("netflix", "Assinaturas & Lazer"),
    ("spotify", "Assinaturas & Lazer"),
    ("amazon prime", "Assinaturas & Lazer"),
    ("prime video", "Assinaturas & Lazer"),
    ("youtube", "Assinaturas & Lazer"),
    ("disney", "Assinaturas & Lazer"),
    ("hbo", "Assinaturas & Lazer"),
    ("max.com", "Assinaturas & Lazer"),
    ("globoplay", "Assinaturas & Lazer"),
    ("apple.com/bill", "Assinaturas & Lazer"),
    ("google storage", "Assinaturas & Lazer"),
    ("google play", "Assinaturas & Lazer"),
    ("deezer", "Assinaturas & Lazer"),
    ("steam", "Assinaturas & Lazer"),
    ("playstation", "Assinaturas & Lazer"),
    ("sony", "Assinaturas & Lazer"),
    ("xbox", "Assinaturas & Lazer"),
    ("microsoft", "Assinaturas & Lazer"),
    ("nintendo", "Assinaturas & Lazer"),
    ("cinema", "Assinaturas & Lazer"),
    ("cinemark", "Assinaturas & Lazer"),
    ("ingresso.com", "Assinaturas & Lazer"),
    ("sympla", "Assinaturas & Lazer"),
    ("eventim", "Assinaturas & Lazer"),
    ("smart fit", "Assinaturas & Lazer"),
    ("bluefit", "Assinaturas & Lazer"),
    ("academia", "Assinaturas & Lazer"),
    ("gympass", "Assinaturas & Lazer"),
    ("totalpass", "Assinaturas & Lazer"),

    # Compras & Vestuário
    ("mercado livre", "Compras"),
    ("mercadolivre", "Compras"),
    ("amazon", "Compras"),
    ("shopee", "Compras"),
    ("aliexpress", "Compras"),
    ("magalu", "Compras"),
    ("magazine luiza", "Compras"),
    ("americanas", "Compras"),
    ("submarino", "Compras"),
    ("kabum", "Compras"),
    ("casas bahia", "Compras"),
    ("ponto frio", "Compras"),
    ("shein", "Compras"),
    ("zara", "Compras"),
    ("renner", "Compras"),
    ("riachuelo", "Compras"),
    ("c&a", "Compras"),
    ("centauro", "Compras"),
    ("netshoes", "Compras"),
    ("dafiti", "Compras"),
    ("nike", "Compras"),
    ("adidas", "Compras"),
    ("boticario", "Compras"),
    ("natura", "Compras"),
    ("sephora", "Compras"),

    # Saúde & Farmácia
    ("farmacia", "Saúde"),
    ("drogaria", "Saúde"),
    ("droga raia", "Saúde"),
    ("drogasil", "Saúde"),
    ("pague menos", "Saúde"),
    ("sao paulo drogaria", "Saúde"),
    ("panvel", "Saúde"),
    ("consulta", "Saúde"),
    ("laboratorio", "Saúde"),
    ("fleury", "Saúde"),
    ("lavoisier", "Saúde"),
    ("hermes pardini", "Saúde"),
    ("unimed", "Saúde"),
    ("amil", "Saúde"),
    ("sulamerica", "Saúde"),
    ("bradesco saude", "Saúde"),
    ("dentista", "Saúde"),
    ("odonto", "Saúde"),
    ("psicolog", "Saúde"),
    ("otica", "Saúde"),

    # Educação
    ("udemy", "Educação"),
    ("alura", "Educação"),
    ("coursera", "Educação"),
    ("faculdade", "Educação"),
    ("universidade", "Educação"),
    ("escola", "Educação"),
    ("colegio", "Educação"),
    ("curso", "Educação"),
    ("livraria", "Educação"),
    ("saraiva", "Educação"),
    ("estante virtual", "Educação"),
    ("concurso", "Educação"),
    ("estrategia concursos", "Educação"),
    ("gran cursos", "Educação"),
    ("qconcursos", "Educação"),

    # Serviços & Tarifas
    ("iof", "Serviços & Tarifas"),
    ("tarifa", "Serviços & Tarifas"),
    ("anuidade", "Serviços & Tarifas"),
    ("juros", "Serviços & Tarifas"),
    ("multa", "Serviços & Tarifas"),
    ("seguro", "Serviços & Tarifas"),
]

# Mapa de categorias do Nubank para categorias padronizadas
NUBANK_CATEGORY_MAP = {
    "restaurante": "Alimentação",
    "supermercado": "Alimentação",
    "alimentação": "Alimentação",
    "transporte": "Transporte",
    "viagem": "Transporte",
    "serviços": "Serviços & Tarifas",
    "educação": "Educação",
    "saúde": "Saúde",
    "lazer": "Assinaturas & Lazer",
    "compras": "Compras",
    "casa": "Moradia",
    "outros": "Outros",
}

# Regras padrão ordenadas por comprimento decrescente da palavra-chave
# para garantir que termos mais específicos (ex: "mercado livre") tenham precedência sobre termos genéricos (ex: "mercado")
SORTED_DEFAULT_CATEGORY_RULES: List[Tuple[str, str]] = sorted(
    DEFAULT_CATEGORY_RULES,
    key=lambda x: len(x[0]),
    reverse=True
)

def normalize_text(text: str) -> str:
    """Remove acentos e converte para minúsculo para facilitar matching."""
    if not text:
        return ""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', text)
    cleaned = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return cleaned.lower().strip()

def categorize_transaction(
    title: str,
    original_category: Optional[str] = None,
    custom_rules: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Categoriza automaticamente uma transação a partir do título, categoria original do banco
    e regras customizadas do usuário.
    """
    norm_title = normalize_text(title)

    # 1. Regras customizadas do usuário (maior prioridade, mais específicas primeiro)
    if custom_rules:
        sorted_custom = sorted(custom_rules, key=lambda r: len(r.get("keyword", "")), reverse=True)
        for rule in sorted_custom:
            kw = normalize_text(rule.get("keyword", ""))
            if kw and kw in norm_title:
                return rule.get("category_name", "Outros")

    # 2. Palavras-chave do dicionário padrão no título (mais específicas primeiro)
    for keyword, cat in SORTED_DEFAULT_CATEGORY_RULES:
        if normalize_text(keyword) in norm_title:
            return cat


    # 3. Categoria original fornecida pelo Nubank (se houver)
    if original_category:
        norm_orig = normalize_text(original_category)
        if norm_orig in NUBANK_CATEGORY_MAP:
            return NUBANK_CATEGORY_MAP[norm_orig]
        for key, val in NUBANK_CATEGORY_MAP.items():
            if key in norm_orig:
                return val

    # 4. Fallback padrão
    return "Outros"

def parse_date_str(date_str: str) -> Tuple[datetime.date, str]:
    """
    Converte uma string de data para objeto date e retorna também a string 'YYYY-MM'.
    Suporta formatos: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD.
    """
    date_str = date_str.strip()
    # Tenta extrair a data se tiver hora junta
    if " " in date_str:
        date_str = date_str.split(" ")[0]
    if "T" in date_str:
        date_str = date_str.split("T")[0]

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d/%m/%y",
        "%d-%m-%y"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt).date()
            month_year = dt.strftime("%Y-%m")
            return dt, month_year
        except ValueError:
            pass

    # Fallback para hoje
    dt = datetime.utcnow().date()
    return dt, dt.strftime("%Y-%m")

def parse_amount(val: Any) -> float:
    """Converte valor numérico ou string (com ponto ou vírgula) para float positivo."""
    if isinstance(val, (int, float)):
        return abs(float(val))
    
    val_str = str(val).strip().replace("R$", "").replace(" ", "")
    # Tratamento de formato brasileiro: 1.234,56 -> 1234.56
    if "," in val_str and "." in val_str:
        if val_str.rfind(",") > val_str.rfind("."):
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        val_str = val_str.replace(",", ".")

    try:
        amount = float(val_str)
        return round(abs(amount), 2)
    except (ValueError, TypeError):
        return 0.0

def parse_nubank_csv(
    content: str,
    custom_rules: Optional[List[Dict[str, str]]] = None
) -> List[Dict[str, Any]]:
    """
    Analisa CSV de fatura de cartão de crédito ou extrato de conta do Nubank.
    Suporta delimitadores ',' e ';'.
    """
    transactions = []
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return transactions

    # Detectar delimitador
    sample = "\n".join(lines[:5])
    delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.reader(lines, delimiter=delimiter)
    header = None
    
    for row in reader:
        if not row or all(c.strip() == "" for c in row):
            continue
        
        # Identificar cabeçalho
        first_col = normalize_text(row[0])
        if first_col in ["date", "data", "dt", "data da transacao"]:
            header = [normalize_text(c) for c in row]
            continue

        if header is None:
            # Caso não tenha linha de cabeçalho formal, tentar inferir pela primeira linha
            header = ["date", "category", "title", "amount"] if len(row) >= 4 else ["date", "title", "amount"]

        # Mapeamento dinâmico de colunas
        date_val = None
        title_val = ""
        amount_val = 0.0
        orig_category = ""

        row_dict = {}
        for idx, col_name in enumerate(header):
            if idx < len(row):
                row_dict[col_name] = row[idx].strip()

        # Extrair data
        for k in ["date", "data", "dt"]:
            if k in row_dict:
                date_val = row_dict[k]
                break

        # Extrair valor
        for k in ["amount", "valor", "amount (brl)", "valor (r$)"]:
            if k in row_dict:
                amount_val = parse_amount(row_dict[k])
                break

        # Extrair título / descrição
        for k in ["title", "titulo", "descricao", "description", "identificador", "estabelecimento", "memo"]:
            if k in row_dict and row_dict[k]:
                title_val = row_dict[k]
                break

        # Extrair categoria original
        for k in ["category", "categoria"]:
            if k in row_dict and row_dict[k]:
                orig_category = row_dict[k]
                break

        # Se não achou pelos nomes, usa posição
        if not date_val and len(row) >= 1:
            date_val = row[0]
        if not title_val and len(row) >= 3:
            title_val = row[2] if len(row) >= 4 else row[1]
        elif not title_val and len(row) >= 2:
            title_val = row[1]
        if amount_val == 0.0 and len(row) >= 3:
            amount_val = parse_amount(row[-1])

        if not date_val or amount_val == 0.0 or not title_val:
            continue

        # Ignorar pagamentos de fatura recebidos (para não duplicar/anular gastos)
        title_norm = normalize_text(title_val)
        if any(ign in title_norm for ign in ["pagamento de fatura", "pagamento recebido", "fatura paga", "transferencia recebida", "estorno"]):
            # Se for pagamento de fatura, não é gasto novo da fatura
            if "pagamento de fatura" in title_norm or "pagamento recebido" in title_norm:
                continue

        dt_obj, month_year = parse_date_str(date_val)
        category = categorize_transaction(title_val, orig_category, custom_rules)

        transactions.append({
            "date": dt_obj,
            "month_year": month_year,
            "title": title_val,
            "amount": amount_val,
            "category": category,
            "original_category": orig_category,
            "payment_method": "Cartão Nubank"
        })

    return transactions

def parse_ofx(
    content: str,
    custom_rules: Optional[List[Dict[str, str]]] = None
) -> List[Dict[str, Any]]:
    """Analisa arquivos OFX bancários (Open Financial Exchange)."""
    transactions = []
    
    # Regex para capturar blocos de transação <STMTTRN>...</STMTTRN>
    blocks = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL | re.IGNORECASE)
    if not blocks:
        # Tentar blocos sem fechamento explícito
        blocks = re.split(r'<STMTTRN>', content, flags=re.IGNORECASE)[1:]

    for block in blocks:
        # Extrair data <DTPOSTED>20240115...
        dt_match = re.search(r'<DTPOSTED>(\d{8})', block, re.IGNORECASE)
        # Extrair valor <TRNAMT>-45.50
        amt_match = re.search(r'<TRNAMT>([-\d\.,]+)', block, re.IGNORECASE)
        # Extrair título <MEMO>... ou <NAME>...
        memo_match = re.search(r'<(?:MEMO|NAME)>(.*?)(?:<|\n|$)', block, re.IGNORECASE)

        if not dt_match or not amt_match:
            continue

        raw_dt = dt_match.group(1)
        date_str = f"{raw_dt[0:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}"
        dt_obj, month_year = parse_date_str(date_str)

        amount_val = parse_amount(amt_match.group(1))
        if amount_val == 0.0:
            continue

        title_val = memo_match.group(1).strip() if memo_match else "Transação OFX"
        category = categorize_transaction(title_val, None, custom_rules)

        transactions.append({
            "date": dt_obj,
            "month_year": month_year,
            "title": title_val,
            "amount": amount_val,
            "category": category,
            "original_category": None,
            "payment_method": "Nubank / OFX"
        })

    return transactions

def parse_raw_text(
    content: str,
    custom_rules: Optional[List[Dict[str, str]]] = None
) -> List[Dict[str, Any]]:
    """
    Analisa texto bruto colado pelo usuário.
    Tenta primeiro como CSV, depois tenta padrões comuns de linha por linha.
    """
    content = content.strip()
    if not content:
        return []

    if "<OFX>" in content or "<STMTTRN>" in content:
        return parse_ofx(content, custom_rules)

    # Tenta CSV
    csv_results = parse_nubank_csv(content, custom_rules)
    if csv_results:
        return csv_results

    # Parser de texto livre linha a linha:
    # Exemplo: "15/01 iFood R$ 45,90" ou "2024-01-10 Uber 19.90"
    transactions = []
    lines = content.splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Regex para achar data no início da linha (DD/MM ou DD/MM/YYYY ou YYYY-MM-DD)
        date_pattern = r'^(\d{2}/\d{2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})'
        amt_pattern = r'(?:R\$?\s*)?([\d\.,]+)$'

        d_match = re.search(date_pattern, line)
        a_match = re.search(amt_pattern, line)

        if d_match and a_match:
            date_part = d_match.group(1)
            # Se a data for só DD/MM, adiciona o ano atual
            if len(date_part) == 5 and "/" in date_part:
                date_part = f"{date_part}/{datetime.utcnow().year}"

            dt_obj, month_year = parse_date_str(date_part)
            amount_val = parse_amount(a_match.group(1))

            # O que sobrou no meio é o título
            title_part = line[d_match.end():a_match.start()].strip()
            if not title_part:
                title_part = "Transação"

            category = categorize_transaction(title_part, None, custom_rules)
            transactions.append({
                "date": dt_obj,
                "month_year": month_year,
                "title": title_part,
                "amount": amount_val,
                "category": category,
                "original_category": None,
                "payment_method": "Fatura Nubank"
            })

    return transactions

def compute_financial_summary(transactions: List[Any]) -> Dict[str, Any]:
    """
    Calcula métricas agregadas gerais, mensais e por categoria.
    Compatível com objetos ORM ou dicionários.
    """
    total_spent = 0.0
    monthly_map: Dict[str, float] = {}
    category_map: Dict[str, float] = {}
    monthly_cat_map: Dict[str, Dict[str, float]] = {}
    months_set = set()

    for t in transactions:
        amount = float(t.amount if hasattr(t, "amount") else t.get("amount", 0.0))
        m_year = str(t.month_year if hasattr(t, "month_year") else t.get("month_year", ""))
        cat = str(t.category if hasattr(t, "category") else t.get("category", "Outros"))

        total_spent += amount
        months_set.add(m_year)

        monthly_map[m_year] = monthly_map.get(m_year, 0.0) + amount
        category_map[cat] = category_map.get(cat, 0.0) + amount

        if m_year not in monthly_cat_map:
            monthly_cat_map[m_year] = {}
        monthly_cat_map[m_year][cat] = monthly_cat_map[m_year].get(cat, 0.0) + amount

    num_months = max(1, len(months_set))
    avg_monthly = round(total_spent / num_months, 2)
    total_spent = round(total_spent, 2)

    # Ordenar meses cronologicamente
    sorted_months = sorted(list(months_set))

    # Maior categoria
    top_category = "N/A"
    top_category_amount = 0.0
    if category_map:
        top_category = max(category_map, key=category_map.get)
        top_category_amount = round(category_map[top_category], 2)

    # Lista formatada para categorias
    categories_breakdown = []
    for cat, val in sorted(category_map.items(), key=lambda x: x[1], reverse=True):
        pct = round((val / total_spent * 100), 1) if total_spent > 0 else 0.0
        categories_breakdown.append({
            "category": cat,
            "total": round(val, 2),
            "percentage": pct
        })

    # Lista formatada para meses
    monthly_breakdown = []
    for m in sorted_months:
        monthly_breakdown.append({
            "month_year": m,
            "total": round(monthly_map[m], 2),
            "categories": {k: round(v, 2) for k, v in monthly_cat_map.get(m, {}).items()}
        })

    return {
        "total_spent": total_spent,
        "total_transactions": len(transactions),
        "months_count": len(months_set),
        "available_months": sorted_months,
        "avg_monthly": avg_monthly,
        "top_category": top_category,
        "top_category_amount": top_category_amount,
        "top_category_percent": round((top_category_amount / total_spent * 100), 1) if total_spent > 0 else 0.0,
        "categories_breakdown": categories_breakdown,
        "monthly_breakdown": monthly_breakdown
    }

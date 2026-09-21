"""
deduplication.py — Motor de Deduplicação Cross-Plataforma de Vagas

Detecta quando a mesma vaga foi publicada em múltiplos portais de emprego
(ex: Gupy, LinkedIn, InfoJobs, Catho, etc.) e consolida em um único registro.
"""

import re
import json
import hashlib
import unicodedata
from typing import Optional, Tuple, List, Dict, Any

# Sufixos e palavras a remover de nomes de empresas para normalização
_COMPANY_CLEAN_PATTERNS = [
    r'\b(ltda|s/?a|s\.a\.|eireli|me|epp|inc|corp|llc|gmbh)\b',
    r'\b(brasil|brazil|do brasil|servicos|tecnologia|solucoes|consultoria|group|grupo)\b',
    r'[^\w\s]',
]

# Tags comuns no título que devem ser limpas para normalização
_TITLE_CLEAN_PATTERNS = [
    r'\[.*?\]',               # [Remoto], [Híbrido], [PCD]
    r'\(.*?\)',               # (PCD), (Home Office), (Vaga Afirmativa)
    r'\b(vaga|oportunidade|banco de talentos|exclusiva|afirmativa|urgente)\b',
    r'\b(pcd|pne|deficiencia)\b',
    r'[^\w\s]',
]

_SENIORITY_NORMALIZATION = {
    'jr': 'junior',
    'pl': 'pleno',
    'sr': 'senior',
    'i': '1',
    'ii': '2',
    'iii': '3',
    'n1': '1',
    'n2': '2',
    'n3': '3',
}


def strip_accents(text: str) -> str:
    """Remove acentos e caracteres diacríticos."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def normalize_company_name(name: str) -> str:
    """Normaliza o nome da empresa para cruzamento entre plataformas."""
    if not name or name.strip().lower() in ("empresa confidencial", "confidencial", "não informada"):
        return "confidencial"
    
    text = strip_accents(name.lower())
    for pat in _COMPANY_CLEAN_PATTERNS:
        text = re.sub(pat, ' ', text)
    
    words = [w for w in text.split() if len(w) > 1]
    return " ".join(words)


def normalize_job_title(title: str) -> str:
    """Normaliza o título do cargo para comparação e deduplicação."""
    if not title:
        return ""
    
    text = strip_accents(title.lower())
    for pat in _TITLE_CLEAN_PATTERNS:
        text = re.sub(pat, ' ', text)
        
    tokens = text.split()
    normalized_tokens = [_SENIORITY_NORMALIZATION.get(tok, tok) for tok in tokens if len(tok) > 1]
    return " ".join(normalized_tokens)


def generate_dedup_hash(company: str, title: str, location: str = "") -> str:
    """
    Gera um hash determinístico de 16 caracteres para busca rápida de duplicatas exatas.
    """
    norm_comp = normalize_company_name(company)
    norm_title = normalize_job_title(title)
    
    # Se a empresa for confidencial, inclui um resumo da localização para evitar falsos positivos
    key = f"{norm_comp}::{norm_title}"
    if norm_comp == "confidencial" and location:
        norm_loc = strip_accents(location.lower()[:15])
        key += f"::{norm_loc}"
        
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def calculate_title_similarity(title_a: str, title_b: str) -> float:
    """
    Calcula similaridade baseada em sobreposição de palavras (Jaccard)
    entre dois títulos de cargo normalizados.
    """
    words_a = set(normalize_job_title(title_a).split())
    words_b = set(normalize_job_title(title_b).split())
    
    if not words_a or not words_b:
        return 0.0
    
    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)
    
    return len(intersection) / len(union)


def is_duplicate(
    candidate: Dict[str, Any],
    existing_jobs: List[Any],
    similarity_threshold: float = 0.80
) -> Tuple[bool, Optional[Any]]:
    """
    Avalia se uma vaga candidata já existe na lista de vagas cadastradas.
    
    Critérios:
    1. Mesma URL/link direto -> Duplicata imediata (100%)
    2. Mesmo dedup_hash -> Duplicata exata (100%)
    3. Mesma empresa normalizada + similaridade de título >= 80% -> Duplicata cross-plataforma
    """
    cand_link = (candidate.get("link") or "").strip()
    cand_company = candidate.get("company") or ""
    cand_title = candidate.get("title") or ""
    cand_hash = generate_dedup_hash(cand_company, cand_title, candidate.get("location") or "")
    
    norm_cand_comp = normalize_company_name(cand_company)
    
    for job in existing_jobs:
        job_link = (getattr(job, 'link', None) or "").strip()
        if cand_link and job_link and cand_link == job_link:
            return True, job
        
        job_hash = getattr(job, 'dedup_hash', None)
        if job_hash and job_hash == cand_hash:
            return True, job
            
        # Comparação difusa caso a empresa não seja 'confidencial'
        job_comp = getattr(job, 'company', '')
        norm_job_comp = normalize_company_name(job_comp)
        
        if norm_cand_comp != "confidencial" and norm_cand_comp == norm_job_comp:
            job_title = getattr(job, 'title', '')
            sim = calculate_title_similarity(cand_title, job_title)
            if sim >= similarity_threshold:
                return True, job
                
    return False, None


def merge_job_sources(existing_sources_json: Optional[str], new_source: str, new_link: str) -> str:
    """
    Adiciona uma nova fonte e link à lista JSON de fontes da vaga sem duplicar.
    """
    sources: List[Dict[str, str]] = []
    if existing_sources_json:
        try:
            parsed = json.loads(existing_sources_json)
            if isinstance(parsed, list):
                sources = parsed
        except Exception:
            sources = []
            
    # Verifica se já existe a fonte com o mesmo link
    already_exists = any(s.get("source") == new_source or s.get("link") == new_link for s in sources)
    if not already_exists:
        sources.append({
            "source": new_source,
            "link": new_link
        })
        
    return json.dumps(sources, ensure_ascii=False)

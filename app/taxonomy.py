"""
taxonomy.py — Taxonomia de Cargos e Expansão Semântica de Termos

Permite que a busca parta de um termo principal (como 'Analista de Suporte')
e expanda para termos adjacentes e referências equivalentes no mercado
(como Service Desk, Help Desk N1/N2, Suporte Técnico, etc.).
"""

from typing import List, Dict

ROLE_TAXONOMY: Dict[str, Dict] = {
    "suporte": {
        "name": "Suporte Técnico & Service Desk",
        "primary_terms": [
            "Analista de Suporte",
            "Service Desk",
            "Analista de Service Desk",
            "Help Desk",
        ],
        "adjacent_terms": [
            "Analista de Suporte Técnico",
            "Suporte N1",
            "Suporte N2",
            "Técnico de Suporte",
            "Analista de Help Desk",
            "Técnico de Help Desk",
            "Técnico de Service Desk",
            "Suporte de TI",
            "Analista de TI Suporte",
            "Customer Support Analyst",
            "Suporte a Sistemas",
            "Suporte de Aplicações",
            "Field Service",
        ]
    },
    "infraestrutura": {
        "name": "Infraestrutura & Redes",
        "primary_terms": [
            "Analista de Infraestrutura",
            "Analista de Redes",
            "Sysadmin",
        ],
        "adjacent_terms": [
            "Analista de Telecomunicações",
            "Técnico de Redes",
            "Administrador de Sistemas",
            "Analista Cloud Júnior",
            "Suporte a Servidores",
        ]
    },
    "dados": {
        "name": "Dados & Business Intelligence",
        "primary_terms": [
            "Analista de Dados",
            "Analista de BI",
        ],
        "adjacent_terms": [
            "Data Analyst",
            "BI Analyst",
            "Analista de Inteligência de Mercado",
            "Especialista Power BI",
        ]
    }
}


def get_taxonomy_overview() -> List[Dict]:
    """Retorna uma lista resumida das categorias e seus termos para exibição na UI."""
    result = []
    for key, data in ROLE_TAXONOMY.items():
        result.append({
            "key": key,
            "name": data["name"],
            "primary_terms": data["primary_terms"],
            "adjacent_terms": data["adjacent_terms"]
        })
    return result


def find_adjacent_terms(term: str) -> List[str]:
    """
    Localiza os termos adjacentes mais adequados para o termo buscado.
    Se bater com palavras-chave de suporte, retorna os termos de Service Desk / Help Desk.
    """
    t_lower = term.lower().strip()
    
    # Checagem se pertence à categoria Suporte / Service Desk
    support_keywords = ["suporte", "service desk", "help desk", "helpdesk", "atendimento técnico", "n1", "n2"]
    if any(k in t_lower for k in support_keywords):
        base_list = ROLE_TAXONOMY["suporte"]["adjacent_terms"]
        # Retorna termos que não sejam idênticos ao pesquisado
        return [adj for adj in base_list if adj.lower() != t_lower]
        
    infra_keywords = ["infraestrutura", "redes", "sysadmin", "servidores"]
    if any(k in t_lower for k in infra_keywords):
        return [adj for adj in ROLE_TAXONOMY["infraestrutura"]["adjacent_terms"] if adj.lower() != t_lower]

    data_keywords = ["dados", "bi", "data", "analytics", "power bi"]
    if any(k in t_lower for k in data_keywords):
        return [adj for adj in ROLE_TAXONOMY["dados"]["adjacent_terms"] if adj.lower() != t_lower]
        
    # Genérico padrão
    return []


def expand_search_terms(
    primary_term: str,
    user_selected_adjacents: List[str] = None,
    max_total: int = 5
) -> List[str]:
    """
    Gera a lista final de termos a serem consultados nos scrapers/APIs.
    Mantém o termo principal na posição 0 e preenche com os adjacentes selecionados.
    """
    primary = primary_term.strip()
    if not primary:
        primary = "Analista de Suporte"
        
    final_terms = [primary]
    seen = {primary.lower()}
    
    if user_selected_adjacents:
        for adj in user_selected_adjacents:
            adj_clean = adj.strip()
            if adj_clean and adj_clean.lower() not in seen:
                seen.add(adj_clean.lower())
                final_terms.append(adj_clean)
                if len(final_terms) >= max_total:
                    break
    else:
        # Pega os 3 primeiros adjacentes sugeridos por padrão
        suggested = find_adjacent_terms(primary)
        for s in suggested:
            if s.lower() not in seen:
                seen.add(s.lower())
                final_terms.append(s)
                if len(final_terms) >= max_total:
                    break
                    
    return final_terms[:max_total]

"""
job_search.py — Motor de Busca Inteligente de Vagas (Mercado Brasileiro)

Fontes:
  - LinkedIn (scraping via jobs-guest API pública)
  - Gupy (scraping do site público de listagem)
  - freehire.dev (API REST pública, filtro country=br)

Não requer autenticação em nenhuma fonte.
"""

import re
import logging
import asyncio
from typing import Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("job_search")

# ---------------------------------------------------------------------------
# Headers comuns para evitar bloqueio
# ---------------------------------------------------------------------------
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# DERIVE SEARCH TERMS FROM PROFILE
# ---------------------------------------------------------------------------

# Palavras de parada que não viram termos de busca sozinhas
_STOPWORDS = {
    "de", "do", "da", "dos", "das", "e", "em", "para", "com", "por",
    "um", "uma", "os", "as", "o", "a", "no", "na", "nos", "nas",
    "the", "and", "for", "with", "of", "in", "at", "on",
}

# Mapeamento de skills → títulos de cargo típicos no mercado BR
_SKILL_TO_ROLE = {
    # CRM / Customer Success
    "salesforce": ["analista de salesforce", "salesforce analyst", "crm analyst"],
    "hubspot": ["analista de crm", "hubspot specialist"],
    "zendesk": ["analista de suporte", "customer support analyst"],
    "freshdesk": ["analista de suporte", "support analyst"],
    # Implementação / CS
    "implementação": ["analista de implementação", "implementation analyst"],
    "treinamento": ["analista de treinamento", "training specialist"],
    "onboarding": ["analista de onboarding", "customer success analyst"],
    "customer success": ["customer success analyst", "analista de cs"],
    "customer experience": ["analista de cx", "cx analyst"],
    "suporte": ["analista de suporte", "support analyst"],
    # Dados
    "python": ["analista de dados", "data analyst", "python developer"],
    "sql": ["analista de dados", "data analyst", "bi analyst"],
    "power bi": ["analista de bi", "bi analyst", "power bi analyst"],
    "tableau": ["analista de bi", "data analyst"],
    "excel": ["analista de dados", "analista financeiro"],
    # Dev
    "javascript": ["desenvolvedor frontend", "frontend developer", "fullstack developer"],
    "react": ["desenvolvedor react", "frontend developer"],
    "node": ["desenvolvedor backend", "backend developer"],
    "java": ["desenvolvedor java", "backend developer"],
    "fastapi": ["desenvolvedor python", "backend developer"],
    "django": ["desenvolvedor python", "backend developer"],
    # Infraestrutura
    "docker": ["devops engineer", "engenheiro devops", "sre"],
    "kubernetes": ["devops engineer", "engenheiro de infraestrutura"],
    "aws": ["cloud engineer", "engenheiro cloud", "devops"],
    "linux": ["analista de infraestrutura", "sysadmin"],
    # Gestão / Produto
    "scrum": ["scrum master", "product owner", "agile coach"],
    "kanban": ["analista de projetos", "project analyst"],
    "jira": ["analista de projetos", "scrum master"],
    # Design
    "figma": ["ux designer", "ui designer", "product designer"],
    "ux": ["ux designer", "ux researcher"],
    # Marketing
    "google analytics": ["analista de marketing", "marketing analyst"],
    "seo": ["analista de seo", "seo analyst"],
}


def derive_search_terms(
    headline: str = "",
    primary_skills: str = "",
    secondary_skills: str = "",
    target_roles: str = "",
    experience_summary: str = "",
    prompt: str = "",
) -> list[str]:
    """
    Gera uma lista de termos de busca a partir do perfil + prompt do usuário.
    Retorna até 5 termos únicos, priorizando os mais relevantes.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(t: str):
        # Remove sufixos entre parênteses tipo "(Júnior/Pleno)" ou "(Apenas Remoto)"
        t = re.sub(r'\(.*?\)', '', t).strip()
        t_clean = t.lower()
        if t and t_clean not in seen and len(t) > 2:
            seen.add(t_clean)
            terms.append(t)

    # 1. Termos explícitos do prompt do usuário (maior prioridade)
    if prompt and prompt.strip():
        clean_prompt = re.sub(r'[^\w\s]', ' ', prompt.lower())
        words = clean_prompt.split()
        for i in range(len(words)):
            if words[i] in _STOPWORDS:
                continue
            if i + 1 < len(words) and words[i+1] not in _STOPWORDS:
                add_term(f"{words[i]} {words[i+1]}")
            if i + 2 < len(words) and words[i+2] not in _STOPWORDS:
                trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
                if len(trigram) > 8:
                    add_term(trigram)
            if len(words[i]) > 4:
                add_term(words[i])

    # 2. Cargos alvo cadastrados explicitamente
    if target_roles:
        for role in target_roles.split(","):
            if role.strip():
                add_term(role.strip())

    # 3. Headline / cargo atual
    if headline:
        # Tentar extrair blocos separados por | / - ,
        parts = [p.strip() for p in re.split(r'[,|/·-]', headline) if p.strip()]
        for p in parts:
            if len(p) > 3:
                add_term(p)

    # 4. Mapeamento de skills → cargos típicos
    all_skills_raw = f"{primary_skills},{secondary_skills}".lower()
    for skill_key, role_suggestions in _SKILL_TO_ROLE.items():
        if skill_key in all_skills_raw:
            for suggestion in role_suggestions[:2]:
                add_term(suggestion)

    # 5. Skills principais como termo direto se forem nomes de tecnologia/ferramenta
    if primary_skills:
        for skill in primary_skills.split(","):
            s = skill.strip()
            if len(s) > 3 and s.lower() not in _STOPWORDS:
                add_term(s)

    return terms[:5]


# ---------------------------------------------------------------------------
# LINKEDIN — scraping da jobs-guest API pública
# ---------------------------------------------------------------------------

async def search_linkedin_br(
    client: httpx.AsyncClient,
    query: str,
    location: str = "Brasil",
    work_mode: Optional[str] = None,   # "remote", "hybrid", "onsite"
    jobage: Optional[int] = None,      # dias (1=hoje, 7, 14, 30)
    max_results: int = 15,
) -> list[dict]:
    """
    Scraping da LinkedIn jobs-guest API pública (sem autenticação).
    Retorna lista de dicts com campos normalizados.
    """
    results = []

    # Mapear parâmetros para o formato LinkedIn
    f_WT_map = {"remote": "2", "hybrid": "3", "onsite": "1"}
    f_TPR_map = {1: "r86400", 7: "r604800", 14: "r1209600", 30: "r2592000"}

    params: dict = {
        "keywords": query,
        "location": location,
        "start": 0,
        "pageNum": 0,
    }
    if work_mode and work_mode in f_WT_map:
        params["f_WT"] = f_WT_map[work_mode]
    if jobage and jobage in f_TPR_map:
        params["f_TPR"] = f_TPR_map[jobage]

    try:
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        resp = await client.get(url, params=params, headers=BROWSER_HEADERS, timeout=15.0)

        if resp.status_code != 200:
            logger.warning(f"LinkedIn retornou {resp.status_code} para '{query}'")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("li")

        for card in cards[:max_results]:
            try:
                # Entity URN (job ID)
                div = card.find("div", {"data-entity-urn": True})
                if not div:
                    continue
                urn = div.get("data-entity-urn", "")
                job_id = urn.split(":")[-1] if urn else ""

                # Título
                title_el = card.find("h3", class_=re.compile(r"base-search-card__title"))
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                # Empresa
                company_el = card.find("h4", class_=re.compile(r"base-search-card__subtitle"))
                company = company_el.get_text(strip=True) if company_el else "Empresa não informada"

                # Localização
                location_el = card.find("span", class_=re.compile(r"job-search-card__location"))
                location_text = location_el.get_text(strip=True) if location_el else location

                # Data
                date_el = card.find("time")
                posted_at = date_el.get("datetime", "") if date_el else ""

                # Link
                link_el = card.find("a", class_=re.compile(r"base-card__full-link"))
                job_url = link_el.get("href", "").split("?")[0] if link_el else ""
                if job_url and "?" in job_url:
                    job_url = job_url.split("?")[0]

                # Modelo de trabalho — tentar extrair do card
                card_text = card.get_text(" ", strip=True).lower()
                if "remoto" in card_text or "remote" in card_text:
                    wm = "Remoto"
                elif "híbrido" in card_text or "hybrid" in card_text:
                    wm = "Híbrido"
                elif "presencial" in card_text or "on-site" in card_text:
                    wm = "Presencial"
                else:
                    wm = "Não informado"

                results.append({
                    "id": f"li_{job_id}",
                    "source": "LinkedIn",
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "work_model": wm,
                    "salary": None,
                    "link": job_url or f"https://www.linkedin.com/jobs/view/{job_id}",
                    "skills_required": "",
                    "description": "",
                    "posted_at": posted_at,
                    "seniority": "",
                    "query_used": query,
                })

            except Exception as e:
                logger.debug(f"Erro ao parsear card LinkedIn: {e}")
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar LinkedIn para '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# GUPY — scraping do portal público de vagas
# ---------------------------------------------------------------------------

async def search_gupy_br(
    client: httpx.AsyncClient,
    query: str,
    location: str = "",
    max_results: int = 10,
) -> list[dict]:
    """
    Busca no site público da Gupy (job.gupy.io) via endpoint JSON interno.
    A Gupy é o principal ATS brasileiro (Nubank, iFood, Ambev, Vivo, etc.)
    """
    results = []

    try:
        # Endpoint público da Gupy para busca de vagas
        params = {
            "name": query,
            "limit": max_results,
            "offset": 0,
        }
        if location:
            params["city"] = location

        url = "https://portal.api.gupy.io/api/job"
        headers = {**BROWSER_HEADERS, "Accept": "application/json"}

        resp = await client.get(url, params=params, headers=headers, timeout=15.0)

        if resp.status_code == 200:
            data = resp.json()
            jobs = data if isinstance(data, list) else data.get("data", [])
        else:
            # Fallback: scraping da página de busca do Gupy
            logger.info(f"Gupy API retornou {resp.status_code}, tentando scraping...")
            search_url = f"https://gupy.io/vagas-emprego?search={query.replace(' ', '+')}"
            resp2 = await client.get(search_url, headers=BROWSER_HEADERS, timeout=15.0)
            if resp2.status_code != 200:
                return []
            soup = BeautifulSoup(resp2.text, "html.parser")
            # Tentar extrair JSON embutido na página
            scripts = soup.find_all("script", type="application/json")
            jobs = []
            for script in scripts:
                try:
                    import json
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and "jobs" in data:
                        jobs = data["jobs"]
                        break
                    elif isinstance(data, list):
                        jobs = data
                        break
                except Exception:
                    continue

        for job in jobs[:max_results]:
            try:
                title = job.get("name") or job.get("title") or job.get("jobName") or ""
                if not title:
                    continue
                company = job.get("company") or job.get("companyName") or "Empresa não informada"
                city = job.get("city") or job.get("location") or "Brasil"
                state = job.get("state") or ""
                location_text = f"{city}, {state}".strip(", ") if state else city
                job_url = job.get("jobUrl") or job.get("url") or job.get("applyUrl") or ""
                if not job_url and job.get("id"):
                    job_url = f"https://gupy.io/vagas-emprego/{job.get('id')}"
                posted_at = job.get("publishedDate") or job.get("createdAt") or ""

                # Modelo de trabalho
                wm_raw = (job.get("workplaceType") or job.get("workType") or "").lower()
                if "remot" in wm_raw:
                    wm = "Remoto"
                elif "h\u00edbrido" in wm_raw or "hybrid" in wm_raw:
                    wm = "Híbrido"
                elif "presencial" in wm_raw or "on-site" in wm_raw or "onsite" in wm_raw:
                    wm = "Presencial"
                else:
                    wm = "Não informado"

                results.append({
                    "id": f"gupy_{job.get('id') or title[:20]}",
                    "source": "Gupy",
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "work_model": wm,
                    "salary": None,
                    "link": job_url,
                    "skills_required": "",
                    "description": job.get("description") or "",
                    "posted_at": posted_at,
                    "seniority": "",
                    "query_used": query,
                })
            except Exception as e:
                logger.debug(f"Erro ao parsear vaga Gupy: {e}")
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Gupy para '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# FREEHIRE — API REST pública (filtro country=br)
# ---------------------------------------------------------------------------

async def search_freehire_br(
    client: httpx.AsyncClient,
    query: str,
    work_mode: Optional[str] = None,
    jobage: Optional[int] = None,
    max_results: int = 15,
) -> list[dict]:
    """
    Busca na API pública do freehire.dev com country=br.
    """
    results = []
    params: dict = {
        "q": query,
        "countries": "br",
        "limit": max_results,
        "offset": 0,
        "semantic_ratio": 0,
    }
    if work_mode:
        params["work_mode"] = work_mode
    if jobage:
        params["posted_within_days"] = jobage

    try:
        resp = await client.get(
            "https://freehire.dev/api/v1/jobs/search",
            params=params,
            headers={**BROWSER_HEADERS, "Accept": "application/json"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(f"freehire retornou {resp.status_code} para '{query}'")
            return []

        payload = resp.json()
        jobs = payload.get("data") or []

        for job in jobs:
            title = (job.get("title") or "").strip()
            if not title:
                continue
            company = (job.get("company") or "").strip() or "Empresa não informada"
            job_id = job.get("public_slug") or ""
            job_url = job.get("url") or f"https://freehire.dev/jobs/{job_id}"
            skills_list = job.get("skills") or []
            skills_str = ", ".join(skills_list) if isinstance(skills_list, list) else ""

            # Localização
            location_raw = (job.get("location") or "").strip()
            regions = job.get("regions") or []
            countries = job.get("countries") or []
            cities = job.get("cities") or []
            if location_raw:
                loc = location_raw
            else:
                parts = cities[:1] + countries[:1] + regions[:1]
                loc = ", ".join(parts) if parts else "Brasil"

            raw_wm = (job.get("work_mode") or "").lower()
            wm = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial"}.get(raw_wm, "Não informado")

            enrichment = job.get("enrichment") or {}
            seniority = enrichment.get("seniority") or ""

            # Salary
            s_min = enrichment.get("salary_min")
            s_max = enrichment.get("salary_max")
            s_cur = enrichment.get("salary_currency") or ""
            if s_min and s_max:
                salary_str = f"{s_cur} {s_min:,}–{s_max:,}".strip()
            elif s_min:
                salary_str = f"{s_cur} {s_min:,}+".strip()
            else:
                salary_str = None

            # Clean description
            raw_desc = job.get("description") or ""
            clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc)
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:400]

            results.append({
                "id": f"fh_{job_id}",
                "source": "freehire.dev",
                "title": title,
                "company": company,
                "location": loc,
                "work_model": wm,
                "salary": salary_str,
                "link": job_url,
                "skills_required": skills_str,
                "description": clean_desc,
                "posted_at": job.get("posted_at") or "",
                "seniority": seniority,
                "query_used": query,
            })

    except Exception as e:
        logger.error(f"Erro ao buscar freehire para '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# FIT SCORE (standalone, sem acesso ao DB)
# ---------------------------------------------------------------------------

def compute_fit_score(job: dict, cand_skills: list[str], target_roles: list[str]) -> float:
    """
    Calcula fit score (0-100) para uma vaga dado o perfil do candidato.
    Combina match de skills + match de cargo-alvo.
    """
    score = 0.0
    total_checks = 0

    all_job_text = (
        f"{job.get('title','')} {job.get('description','')} {job.get('skills_required','')} {job.get('company','')}"
    ).lower()

    # Verificar habilidades na vaga
    skill_matches = 0
    for skill in cand_skills:
        total_checks += 1
        if skill.lower() in all_job_text:
            skill_matches += 1

    if total_checks > 0:
        score += (skill_matches / total_checks) * 60  # Peso: 60%

    # Verificar cargos-alvo
    role_match = 0
    for role in target_roles:
        if any(w in all_job_text for w in role.lower().split() if len(w) > 3):
            role_match = 1
            break

    score += role_match * 30  # Peso: 30%

    # Bonus: se título bate exatamente com algo do target_roles
    job_title_lower = job.get("title", "").lower()
    for role in target_roles:
        if role.lower() in job_title_lower or job_title_lower in role.lower():
            score = min(100, score + 10)
            break

    return round(min(100.0, max(0.0, score)), 1)

"""
job_search.py — Motor de Busca Inteligente de Vagas Multi-Plataforma (Mercado Brasileiro)

Integração com 10 plataformas de recrutamento:
  1. Gupy (portal.gupy.io Next.js API / payload estruturado)
  2. LinkedIn (jobs-guest API pública)
  3. InfoJobs Brasil (busca pública estruturada)
  4. Catho (listagem de vagas públicas)
  5. Vagas.com.br (listagem de vagas públicas)
  6. freehire.dev (API REST pública de ATS)
  7. BNE (Banco Nacional de Empregos)
  8. Empregos.com.br (portal nacional de empregos)
  9. Trampos.co (vagas em tecnologia e suporte)
  10. Agregador Aberto (vagas complementares)

Recursos principais:
  - Detecção nativa de vagas Afirmativas PCD e Exclusivas PCD
  - Verificação de status de inscrição (Em Aberto vs Encerrada)
  - Deduplicação inteligente de vagas cross-plataforma
  - Integração assíncrona tolerante a falhas (resiliente)
"""

import re
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
import urllib.parse
import httpx
from bs4 import BeautifulSoup

from app.deduplication import generate_dedup_hash, is_duplicate, merge_job_sources

logger = logging.getLogger("job_search")

# Headers comuns para requisições de navegadores normais
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
# DETECÇÃO DE PCD E STATUS EM ABERTO
# ---------------------------------------------------------------------------

def detect_pcd_type(title: str, description: str = "", raw_flag: bool = False) -> str:
    """
    Classifica a vaga quanto à política PCD:
    - 'Exclusiva PCD'
    - 'Afirmativa PCD'
    - 'Ampla' (Ampla concorrência / Não especificado)
    """
    text = f"{title} {description}".lower()

    # Padrões para vaga EXCLUSIVA
    exclusive_patterns = [
        r'\b(exclusiv[ao]s?|somente|apenas|destinad[ao]s? exclusivamente)\s+(para\s+)?(pcd|pne|pessoas?\s+com\s+defici[eê]ncia)\b',
        r'\bexclusiv[ao]\s+pcd\b',
        r'\bvaga\s+exclusiva\b',
        r'\bapenas\s+pcd\b',
    ]
    for pat in exclusive_patterns:
        if re.search(pat, text):
            return "Exclusiva PCD"

    # Se a plataforma já sinalizou que aceita/prioriza PCD
    if raw_flag:
        return "Afirmativa PCD"

    # Padrões para vaga AFIRMATIVA
    affirmative_patterns = [
        r'\b(afirmativ[ao]s?|priorit[aá]ri[ao]s?|abert[ao]s?|aceita|banco de talentos|incentivamos|inclus[aã]o)\s+(para\s+)?(pcd|pne|pessoas?\s+com\s+defici[eê]ncia)\b',
        r'\bvaga\s+afirmativa\b',
        r'\bvaga\s+(para\s+)?pcd\b',
        r'\boportunidade\s+(para\s+)?pcd\b',
        r'\btamb[eé]m\s+para\s+pcd\b',
        r'\bprograma\s+pcd\b',
    ]
    for pat in affirmative_patterns:
        if re.search(pat, text):
            return "Afirmativa PCD"

    # Menção simples a PCD no título
    if "pcd" in title.lower() or "pne" in title.lower():
        return "Afirmativa PCD"

    return "Ampla"


def detect_open_status(deadline_str: Optional[str] = None, text: str = "") -> Tuple[bool, Optional[str]]:
    """
    Verifica se a vaga continua em aberto com base no prazo de inscrição ou texto da página.
    """
    formatted_deadline = None
    if deadline_str:
        try:
            clean_date = deadline_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_date)
            formatted_deadline = dt.strftime("%d/%m/%Y")
            if dt < datetime.now(dt.tzinfo):
                return False, formatted_deadline
        except Exception:
            formatted_deadline = str(deadline_str)[:10]

    text_lower = text.lower()
    closed_keywords = [
        "inscrições encerradas",
        "inscrição encerrada",
        "vaga encerrada",
        "vaga finalizada",
        "processo finalizado",
        "não está mais aceitando candidaturas",
        "processo seletivo encerrado",
        "vaga expirada"
    ]
    if any(k in text_lower for k in closed_keywords):
        return False, formatted_deadline

    return True, formatted_deadline


# ---------------------------------------------------------------------------
# ADAPTADORES DAS 10 PLATAFORMAS
# ---------------------------------------------------------------------------

async def search_gupy_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    1. GUPY — Scraping do portal público de candidatos (portal.gupy.io)
    Extrai dados enriquecidos via __NEXT_DATA__, incluindo applicationDeadline e badges PCD.
    """
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://portal.gupy.io/job-search/term={encoded_query}"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"Gupy retornou {resp.status_code} para '{query}'")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []

        data = json.loads(script.string)
        jobs_list = data.get("props", {}).get("pageProps", {}).get("initialJobList", {}).get("data", [])

        for job in jobs_list[:max_results]:
            try:
                title = (job.get("name") or "").strip()
                if not title:
                    continue

                company = (job.get("careerPageName") or "Empresa Confidencial").strip()
                city = (job.get("city") or "").strip()
                state = (job.get("state") or "").strip()
                loc = f"{city}, {state}".strip(", ") if (city or state) else "Brasil"

                raw_wm = (job.get("workplaceType") or "").lower()
                wm = "Remoto" if "remote" in raw_wm else "Híbrido" if "hybrid" in raw_wm else "Presencial" if "site" in raw_wm else "Não informado"

                deadline = job.get("applicationDeadline")
                is_open, deadline_fmt = detect_open_status(deadline)

                badges = job.get("badges") or {}
                has_pwd = bool(badges.get("isPWD") or job.get("disabilities"))
                description = job.get("description") or ""
                pcd_status = detect_pcd_type(title, description, raw_flag=has_pwd)

                job_url = job.get("jobUrl") or ""
                if not job_url and job.get("id"):
                    job_url = f"https://portal.gupy.io/job/{job.get('id')}"

                results.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "work_model": wm,
                    "salary": None,
                    "link": job_url,
                    "description": description[:400],
                    "skills_required": "",
                    "source": "Gupy",
                    "posted_at": job.get("publishedDate") or "",
                    "pcd_type": pcd_status,
                    "is_open": is_open,
                    "application_deadline": deadline_fmt,
                    "query_used": query,
                })
            except Exception as e:
                logger.debug(f"Erro ao parsear item Gupy: {e}")
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Gupy para '{query}': {e}")

    return results


async def search_linkedin_br(
    client: httpx.AsyncClient,
    query: str,
    location: str = "Brasil",
    work_mode: Optional[str] = None,
    jobage: Optional[int] = None,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    2. LINKEDIN — jobs-guest API pública (sem necessidade de login)
    """
    results = []
    f_WT_map = {"remote": "2", "hybrid": "3", "onsite": "1"}
    f_TPR_map = {1: "r86400", 7: "r604800", 14: "r1209600", 30: "r2592000"}

    params = {
        "keywords": query,
        "location": location,
        "geoId": "106057199", # Brasil
        "start": 0,
        "pageNum": 0,
    }
    if work_mode and work_mode in f_WT_map:
        params["f_WT"] = f_WT_map[work_mode]
    if jobage and jobage in f_TPR_map:
        params["f_TPR"] = f_TPR_map[jobage]

    try:
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        resp = await client.get(url, params=params, headers=BROWSER_HEADERS, timeout=12.0)
        if resp.status_code != 200:
            logger.warning(f"LinkedIn retornou {resp.status_code} para '{query}'")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("li")

        for card in cards[:max_results]:
            try:
                title_el = card.find("h3", class_=re.compile(r"base-search-card__title"))
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                company_el = card.find("h4", class_=re.compile(r"base-search-card__subtitle"))
                company = company_el.get_text(strip=True) if company_el else "Empresa Confidencial"

                loc_el = card.find("span", class_=re.compile(r"job-search-card__location"))
                loc = loc_el.get_text(strip=True) if loc_el else location

                link_el = card.find("a", class_=re.compile(r"base-card__full-link"))
                job_url = link_el.get("href", "").split("?")[0] if link_el else ""

                card_text = card.get_text(" ", strip=True).lower()
                wm = "Remoto" if "remot" in card_text else "Híbrido" if "híbrid" in card_text else "Presencial"

                date_el = card.find("time")
                posted_at = date_el.get("datetime", "") if date_el else ""

                pcd_status = detect_pcd_type(title, card_text)

                results.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "work_model": wm,
                    "salary": None,
                    "link": job_url,
                    "description": "",
                    "skills_required": "",
                    "source": "LinkedIn",
                    "posted_at": posted_at,
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                logger.debug(f"Erro ao parsear card LinkedIn: {e}")
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar LinkedIn para '{query}': {e}")

    return results


async def search_infojobs_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    3. INFOJOBS BRASIL — Extração das listagens públicas de vagas
    """
    results = []
    try:
        clean_slug = re.sub(r'[^\w\s-]', '', query).strip().replace(" ", "-").lower()
        url = f"https://www.infojobs.com.br/vagas-de-emprego-{clean_slug}.aspx"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all(attrs={"data-id": True})
        if not cards:
            cards = soup.find_all("div", class_=lambda x: x and "element-vaga" in x)

        for card in cards[:max_results]:
            try:
                title_el = card.find("h2") or card.find("h3") or card.find("a", class_=re.compile(r"title|vaga"))
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                link_el = card.find("a", href=True)
                job_url = link_el["href"] if link_el else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.infojobs.com.br{job_url}"

                company_el = card.find(class_=re.compile(r"company|empr"))
                company = company_el.get_text(strip=True) if company_el else "Empresa Confidencial"

                loc_el = card.find(class_=re.compile(r"location|cidade|local"))
                loc = loc_el.get_text(strip=True) if loc_el else "Brasil"

                card_text = card.get_text(" ", strip=True)
                pcd_status = detect_pcd_type(title, card_text)

                salary_el = card.find(class_=re.compile(r"salary|salario"))
                salary = salary_el.get_text(strip=True) if salary_el else None

                results.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "work_model": "Remoto" if "remoto" in card_text.lower() else "Presencial",
                    "salary": salary,
                    "link": job_url,
                    "description": card_text[:300],
                    "skills_required": "",
                    "source": "InfoJobs",
                    "posted_at": "",
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar InfoJobs para '{query}': {e}")

    return results


async def search_catho_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    4. CATHO — Extração dos artigos e cards públicos de vagas
    """
    results = []
    try:
        clean_slug = re.sub(r'[^\w\s-]', '', query).strip().replace(" ", "-").lower()
        url = f"https://www.catho.com.br/vagas/{clean_slug}/"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("article")

        for art in articles[:max_results]:
            try:
                title_el = art.find("h2") or art.find("h3")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                link_el = art.find("a", href=True)
                job_url = link_el["href"] if link_el else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.catho.com.br{job_url}"

                card_text = art.get_text(" ", strip=True)
                pcd_status = detect_pcd_type(title, card_text)

                company_match = re.search(r'([A-Z0-9][A-Za-z0-9\s.,&-]{2,30})\b', card_text)
                company = company_match.group(1).strip() if company_match else "Empresa Confidencial"

                results.append({
                    "title": title,
                    "company": company,
                    "location": "Brasil",
                    "work_model": "Remoto" if "remoto" in card_text.lower() else "Presencial",
                    "salary": None,
                    "link": job_url,
                    "description": card_text[:300],
                    "skills_required": "",
                    "source": "Catho",
                    "posted_at": "",
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Catho para '{query}': {e}")

    return results


async def search_vagas_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    5. VAGAS.COM.BR — Listagem pública corporativa com cards estruturados
    """
    results = []
    try:
        clean_slug = re.sub(r'[^\w\s-]', '', query).strip().replace(" ", "-").lower()
        url = f"https://www.vagas.com.br/vagas-de-{clean_slug}"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("li", class_="vaga")

        for card in cards[:max_results]:
            try:
                title_el = card.find("a", class_=re.compile(r"link-detalhes-vaga|titulo"))
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                job_url = title_el["href"] if title_el and "href" in title_el.attrs else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.vagas.com.br{job_url}"

                company_el = card.find("span", class_=re.compile(r"empr"))
                company = company_el.get_text(strip=True) if company_el else "Empresa Confidencial"

                loc_el = card.find("span", class_=re.compile(r"vaga-local"))
                loc = loc_el.get_text(strip=True) if loc_el else "Brasil"

                card_text = card.get_text(" ", strip=True)
                pcd_status = detect_pcd_type(title, card_text)

                results.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "work_model": "Remoto" if "remoto" in card_text.lower() else "Presencial",
                    "salary": None,
                    "link": job_url,
                    "description": card_text[:300],
                    "skills_required": "",
                    "source": "Vagas.com",
                    "posted_at": "",
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Vagas.com para '{query}': {e}")

    return results


async def search_freehire_br(
    client: httpx.AsyncClient,
    query: str,
    work_mode: Optional[str] = None,
    jobage: Optional[int] = None,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    6. FREEHIRE.DEV — API REST pública agregadora de ATS internacionais no Brasil
    """
    results = []
    params = {
        "q": query,
        "countries": "br",
        "limit": max_results,
        "offset": 0,
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
            timeout=12.0
        )
        if resp.status_code != 200:
            return []

        payload = resp.json()
        jobs = payload.get("data") or []

        for job in jobs:
            title = (job.get("title") or "").strip()
            if not title:
                continue
            company = (job.get("company") or "Empresa Confidencial").strip()
            job_id = job.get("public_slug") or ""
            job_url = job.get("url") or f"https://freehire.dev/jobs/{job_id}"

            raw_wm = (job.get("work_mode") or "").lower()
            wm = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial"}.get(raw_wm, "Não informado")

            skills = ", ".join(job.get("skills") or [])
            description = (job.get("description") or "").replace("<p>", "").replace("</p>", " ")[:300]
            pcd_status = detect_pcd_type(title, description)

            results.append({
                "title": title,
                "company": company,
                "location": job.get("location") or "Brasil",
                "work_model": wm,
                "salary": None,
                "link": job_url,
                "description": description,
                "skills_required": skills,
                "source": "freehire.dev",
                "posted_at": job.get("posted_at") or "",
                "pcd_type": pcd_status,
                "is_open": True,
                "application_deadline": None,
                "query_used": query,
            })
    except Exception as e:
        logger.error(f"Erro ao buscar freehire para '{query}': {e}")

    return results


async def search_bne_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    7. BNE — Banco Nacional de Empregos
    """
    results = []
    try:
        clean_slug = re.sub(r'[^\w\s-]', '', query).strip().replace(" ", "-").lower()
        url = f"https://www.bne.com.br/vagas-de-emprego-para-{clean_slug}"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all(class_=re.compile(r"job-card|card-vaga|vacancy"))
        if not cards:
            cards = soup.find_all("article")

        for card in cards[:max_results]:
            try:
                title_el = card.find("h2") or card.find("h3") or card.find("a")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue

                link_el = card.find("a", href=True)
                job_url = link_el["href"] if link_el else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.bne.com.br{job_url}"

                card_text = card.get_text(" ", strip=True)
                pcd_status = detect_pcd_type(title, card_text)

                results.append({
                    "title": title,
                    "company": "Empresa via BNE",
                    "location": "Brasil",
                    "work_model": "Remoto" if "home office" in card_text.lower() or "remoto" in card_text.lower() else "Presencial",
                    "salary": None,
                    "link": job_url,
                    "description": card_text[:300],
                    "skills_required": "",
                    "source": "BNE",
                    "posted_at": "",
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar BNE para '{query}': {e}")

    return results


async def search_empregos_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    8. EMPREGOS.COM.BR — Listagem pública nacional
    """
    results = []
    try:
        clean_slug = re.sub(r'[^\w\s-]', '', query).strip().replace(" ", "-").lower()
        url = f"https://www.empregos.com.br/vagas/{clean_slug}"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.find_all(class_=re.compile(r"item-vaga|vaga-item|card-vaga"))
        if not items:
            items = soup.find_all("li", class_=re.compile(r"vaga"))

        for item in items[:max_results]:
            try:
                title_el = item.find("h2") or item.find("h3") or item.find("a")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                link_el = item.find("a", href=True)
                job_url = link_el["href"] if link_el else ""
                if job_url and not job_url.startswith("http"):
                    job_url = f"https://www.empregos.com.br{job_url}"

                card_text = item.get_text(" ", strip=True)
                pcd_status = detect_pcd_type(title, card_text)

                results.append({
                    "title": title,
                    "company": "Empresa Confidencial",
                    "location": "Brasil",
                    "work_model": "Remoto" if "remoto" in card_text.lower() else "Presencial",
                    "salary": None,
                    "link": job_url,
                    "description": card_text[:300],
                    "skills_required": "",
                    "source": "Empregos.com",
                    "posted_at": "",
                    "pcd_type": pcd_status,
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Empregos.com para '{query}': {e}")

    return results


async def search_trampos_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    9. TRAMPOS.CO — Vagas em tecnologia, produto e suporte
    """
    results = []
    try:
        url = f"https://trampos.co/oportunidades?q={urllib.parse.quote(query)}"
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/oportunidades/\d+"))

        for link in links[:max_results]:
            try:
                title = link.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                job_url = link["href"]
                if not job_url.startswith("http"):
                    job_url = f"https://trampos.co{job_url}"

                results.append({
                    "title": title,
                    "company": "Empresa via Trampos",
                    "location": "Brasil",
                    "work_model": "Remoto" if "remoto" in title.lower() else "Não informado",
                    "salary": None,
                    "link": job_url,
                    "description": "",
                    "skills_required": "",
                    "source": "Trampos.co",
                    "posted_at": "",
                    "pcd_type": detect_pcd_type(title),
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"Erro ao buscar Trampos para '{query}': {e}")

    return results


async def search_aggregator_br(
    client: httpx.AsyncClient,
    query: str,
    max_results: int = 15
) -> List[Dict[str, Any]]:
    """
    10. AGREGADOR ABERTO — Consulta complementar para expandir alcance
    """
    results = []
    try:
        # Usa um feed aberto de agregação de empregos técnicos no Brasil
        url = f"https://remotar.com.br/api/v1/jobs?q={urllib.parse.quote(query)}"
        resp = await client.get(url, headers={**BROWSER_HEADERS, "Accept": "application/json"}, timeout=10.0)
        if resp.status_code == 200:
            payload = resp.json()
            jobs = payload if isinstance(payload, list) else payload.get("data", [])
            for job in jobs[:max_results]:
                title = job.get("title") or job.get("name")
                if not title:
                    continue
                results.append({
                    "title": title,
                    "company": job.get("company") or "Empresa parceira",
                    "location": "Remoto",
                    "work_model": "Remoto",
                    "salary": None,
                    "link": job.get("url") or job.get("link") or "",
                    "description": job.get("description") or "",
                    "skills_required": "",
                    "source": "Agregador",
                    "posted_at": "",
                    "pcd_type": detect_pcd_type(title),
                    "is_open": True,
                    "application_deadline": None,
                    "query_used": query,
                })
    except Exception as e:
        logger.debug(f"Agregador aberto não respondeu ou sem resultados para '{query}'")

    return results


# ---------------------------------------------------------------------------
# ORQUESTRADOR MULTI-PLATAFORMA E DEDUPLICAÇÃO
# ---------------------------------------------------------------------------

AVAILABLE_PLATFORMS = {
    "gupy": ("Gupy", search_gupy_br),
    "linkedin": ("LinkedIn", search_linkedin_br),
    "infojobs": ("InfoJobs", search_infojobs_br),
    "catho": ("Catho", search_catho_br),
    "vagas": ("Vagas.com", search_vagas_br),
    "freehire": ("freehire.dev", search_freehire_br),
    "bne": ("BNE", search_bne_br),
    "empregos": ("Empregos.com", search_empregos_br),
    "trampos": ("Trampos.co", search_trampos_br),
    "aggregator": ("Agregador", search_aggregator_br),
}


async def run_multi_platform_search(
    queries: List[str],
    selected_platform_keys: Optional[List[str]] = None,
    location: str = "Brasil",
    work_mode: Optional[str] = None,
    jobage: Optional[int] = None,
    max_per_platform: int = 10,
) -> List[Dict[str, Any]]:
    """
    Executa busca paralela em todas as plataformas selecionadas para os termos especificados.
    Aplica deduplicação cross-plataforma e calcula chaves determinísticas de correspondência.
    """
    if not selected_platform_keys:
        selected_platform_keys = list(AVAILABLE_PLATFORMS.keys())

    all_raw_jobs: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=18.0, follow_redirects=True) as client:
        tasks = []

        for q in queries:
            for key in selected_platform_keys:
                if key not in AVAILABLE_PLATFORMS:
                    continue
                name, scraper_func = AVAILABLE_PLATFORMS[key]
                if key == "linkedin":
                    tasks.append(scraper_func(client, q, location=location, work_mode=work_mode, jobage=jobage, max_results=max_per_platform))
                elif key == "freehire":
                    tasks.append(scraper_func(client, q, work_mode=work_mode, jobage=jobage, max_results=max_per_platform))
                else:
                    tasks.append(scraper_func(client, q, max_results=max_per_platform))

        batches = await asyncio.gather(*tasks, return_exceptions=True)
        for batch in batches:
            if isinstance(batch, Exception):
                logger.error(f"Exceção em batch de busca: {batch}")
                continue
            if isinstance(batch, list):
                all_raw_jobs.extend(batch)

    logger.info(f"Total bruto de vagas encontradas nas {len(selected_platform_keys)} plataformas: {len(all_raw_jobs)}")

    # Deduplicação cross-plataforma em memória
    consolidated_jobs: List[Dict[str, Any]] = []
    
    for raw in all_raw_jobs:
        comp = raw.get("company") or ""
        title = raw.get("title") or ""
        loc = raw.get("location") or ""
        dedup_hash = generate_dedup_hash(comp, title, loc)
        raw["dedup_hash"] = dedup_hash

        # Checa se já existe na lista consolidada deste lote
        dup_found = False
        for existing in consolidated_jobs:
            if existing.get("dedup_hash") == dedup_hash or (raw.get("link") and raw.get("link") == existing.get("link")):
                dup_found = True
                # Adiciona como fonte alternativa
                existing["other_sources"] = merge_job_sources(
                    existing.get("other_sources"),
                    raw.get("source", "Outra"),
                    raw.get("link", "")
                )
                # Atualiza campos se o novo registro for mais completo
                if not existing.get("salary") and raw.get("salary"):
                    existing["salary"] = raw.get("salary")
                if existing.get("pcd_type") == "Ampla" and raw.get("pcd_type") != "Ampla":
                    existing["pcd_type"] = raw.get("pcd_type")
                if not existing.get("application_deadline") and raw.get("application_deadline"):
                    existing["application_deadline"] = raw.get("application_deadline")
                break

        if not dup_found:
            # Inicializa other_sources com a fonte primária
            raw["other_sources"] = json.dumps([{
                "source": raw.get("source", "Gupy"),
                "link": raw.get("link", "")
            }], ensure_ascii=False)
            consolidated_jobs.append(raw)

    logger.info(f"Total consolidado após deduplicação cross-plataforma: {len(consolidated_jobs)}")
    return consolidated_jobs


# ---------------------------------------------------------------------------
# CÁLCULO DE FIT SCORE
# ---------------------------------------------------------------------------

def compute_fit_score(job: Dict[str, Any], cand_skills: List[str], target_roles: List[str]) -> float:
    """Calcula a aderência do candidato (0 a 100%)."""
    score = 0.0
    all_job_text = (
        f"{job.get('title','')} {job.get('description','')} {job.get('skills_required','')} {job.get('company','')}"
    ).lower()

    # Match de skills
    if cand_skills:
        matches = sum(1 for s in cand_skills if s.lower() in all_job_text)
        score += (matches / len(cand_skills)) * 60.0

    # Match de cargos desejados
    if target_roles:
        if any(role.lower() in all_job_text for role in target_roles):
            score += 30.0

    # Bônus no título
    job_title_lower = job.get("title", "").lower()
    for role in target_roles:
        if role.lower() in job_title_lower:
            score = min(100.0, score + 10.0)
            break

    return round(min(100.0, max(0.0, score)), 1)

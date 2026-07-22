import logging
import re
import unicodedata
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from datetime import datetime
from app.models import TargetCity, Concurso
from app.telegram import notify_new_concursos

logger = logging.getLogger("concurso_scraper")

def remove_accents(input_str: str) -> str:
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
}

async def fetch_pci_concursos(db: Session, target_cities: list[TargetCity]) -> list[dict]:
    found = []
    # Lista de páginas do PCI Concursos (ex: São Paulo, Sudeste)
    urls = [
        "https://www.pciconcursos.com.br/concursos/sp/",
        "https://www.pciconcursos.com.br/concursos/sudeste/"
    ]

    city_names = [c.name.strip() for c in target_cities if c.active]
    normalized_cities = {remove_accents(c): c for c in city_names}

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"PCI Concursos retornou status {resp.status_code} para {url}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                blocks = soup.find_all("div", class_="ca")

                for block in blocks:
                    link_tag = block.find("a", href=True)
                    if not link_tag:
                        continue

                    title = link_tag.text.strip()
                    link = link_tag["href"]
                    if not link.startswith("http"):
                        link = "https://www.pciconcursos.com.br" + link

                    # Extração de detalhes
                    text_block = block.get_text(" ", strip=True)
                    normalized_text = remove_accents(text_block)

                    # Verificar se alguma cidade cadastrada é mencionada no título ou texto do concurso
                    matched_city = None
                    for norm_city, original_city in normalized_cities.items():
                        # Regex boundary para evitar match parcial incorreto
                        if re.search(r'\b' + re.escape(norm_city) + r'\b', normalized_text):
                            matched_city = original_city
                            break

                    if matched_city:
                        # Extrair vagas e salários se presentes no texto
                        vacancies = "Não especificado"
                        vac_match = re.search(r'(\d+\s*vaga[s]?)', text_block, re.IGNORECASE)
                        if vac_match:
                            vacancies = vac_match.group(1)

                        salary = "Não especificado"
                        sal_match = re.search(r'(R\$\s*[\d\.,]+)', text_block, re.IGNORECASE)
                        if sal_match:
                            salary = sal_match.group(1)

                        status = "Inscrições / Notícia"
                        if "inscrições abertas" in text_block.lower():
                            status = "Inscrições Abertas"
                        elif "prorrogad" in text_block.lower():
                            status = "Inscrições Prorrogadas"

                        found.append({
                            "title": title,
                            "link": link,
                            "city": matched_city,
                            "state": "SP",
                            "status": status,
                            "vacancies": vacancies,
                            "salary": salary,
                            "source": "PCI Concursos"
                        })
            except Exception as e:
                logger.error(f"Erro ao raspar {url} no PCI Concursos: {e}")

    return found

async def fetch_jc_concursos(db: Session, target_cities: list[TargetCity]) -> list[dict]:
    found = []
    url = "https://jcconcursos.com.br/concursos/sp"
    city_names = [c.name.strip() for c in target_cities if c.active]
    normalized_cities = {remove_accents(c): c for c in city_names}

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                articles = soup.find_all(["article", "div"], class_=re.compile("job|card|concurso", re.I))

                for item in articles:
                    link_tag = item.find("a", href=True)
                    if not link_tag:
                        continue

                    title = link_tag.text.strip()
                    if not title or len(title) < 5:
                        continue

                    link = link_tag["href"]
                    if not link.startswith("http"):
                        link = "https://jcconcursos.com.br" + link

                    text_block = item.get_text(" ", strip=True)
                    normalized_text = remove_accents(text_block)

                    matched_city = None
                    for norm_city, original_city in normalized_cities.items():
                        if re.search(r'\b' + re.escape(norm_city) + r'\b', normalized_text):
                            matched_city = original_city
                            break

                    if matched_city:
                        found.append({
                            "title": title,
                            "link": link,
                            "city": matched_city,
                            "state": "SP",
                            "status": "Acompanhamento JC",
                            "vacancies": "Consulte o edital",
                            "salary": "Consulte o edital",
                            "source": "JC Concursos"
                        })
        except Exception as e:
            logger.error(f"Erro ao raspar JC Concursos: {e}")

    return found

async def run_scraper_job(db: Session) -> dict:
    logger.info("Iniciando execução do scraper de concursos...")
    target_cities = db.query(TargetCity).filter(TargetCity.active == True).all()

    if not target_cities:
        logger.info("Nenhuma cidade de interesse cadastrada para raspagem.")
        return {"status": "success", "message": "Nenhuma cidade cadastrada", "new_concursos": 0}

    results = []
    pci_results = await fetch_pci_concursos(db, target_cities)
    jc_results = await fetch_jc_concursos(db, target_cities)

    results.extend(pci_results)
    results.extend(jc_results)

    new_items: list[Concurso] = []
    for item in results:
        # Verificar se link já existe no banco
        existing = db.query(Concurso).filter(Concurso.link == item["link"]).first()
        if not existing:
            concurso = Concurso(
                title=item["title"],
                link=item["link"],
                city=item["city"],
                state=item["state"],
                status=item["status"],
                vacancies=item["vacancies"],
                salary=item["salary"],
                source=item["source"],
                detected_at=datetime.utcnow(),
                notified=False
            )
            db.add(concurso)
            new_items.append(concurso)

    if new_items:
        db.commit()
        # Atualizar os IDs criados no commit
        for item in new_items:
            db.refresh(item)
        logger.info(f"{len(new_items)} novos concursos encontrados e gravados no banco.")
        # Disparar alertas Telegram
        notified_count = await notify_new_concursos(new_items, db)
        logger.info(f"{notified_count} alertas disparados via Telegram.")
    else:
        logger.info("Nenhum concurso novo detectado nesta rodada.")

    return {
        "status": "success",
        "scraped_total": len(results),
        "new_concursos": len(new_items)
    }

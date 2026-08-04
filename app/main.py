import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import httpx

from app.database import Base, engine, get_db, SessionLocal
from app import models
from app.scraper import run_scraper_job
from app.telegram import send_telegram_message, get_telegram_config


# Configuração de logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("concurso_app")

# Inicialização do APScheduler
scheduler = AsyncIOScheduler()

async def scheduled_scraper():
    db = SessionLocal()
    try:
        await run_scraper_job(db)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Criar tabelas se não existirem
    Base.metadata.create_all(bind=engine)

    # Configurar agendamento diário (padrão 07:00 AM)
    hour = int(os.getenv("SCRAPER_CRON_HOUR", "7"))
    minute = int(os.getenv("SCRAPER_CRON_MINUTE", "0"))
    scheduler.add_job(
        scheduled_scraper,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_concurso_scraper",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"APScheduler iniciado com job diário agendado para {hour:02d}:{minute:02d}.")

    yield

    scheduler.shutdown()
    logger.info("APScheduler finalizado.")

app = FastAPI(title="Concurso Monitor & Study Tracker", version="1.0.0", lifespan=lifespan)

# Configuração de arquivos estáticos e templates HTML
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- SCHEMAS PYDANTIC ---

class TargetCityCreate(BaseModel):
    name: str
    uf: Optional[str] = "SP"

class TelegramConfigUpdate(BaseModel):
    bot_token: str
    chat_id: str
    enabled: bool = True

class JobPositionCreate(BaseModel):
    name: str
    target_exam: Optional[str] = None

class SubjectCreate(BaseModel):
    name: str
    weight: Optional[float] = 1.0

class TopicCreate(BaseModel):
    title: str

class TopicUpdate(BaseModel):
    theory_percent: Optional[int] = 0
    reviews_count: Optional[int] = 0
    questions_done: Optional[int] = 0
    questions_correct: Optional[int] = 0
    notes: Optional[str] = None

class CandidateProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    primary_skills: Optional[str] = None
    secondary_skills: Optional[str] = None
    experience_summary: Optional[str] = None
    target_roles: Optional[str] = None
    dealbreakers: Optional[str] = None

class JobSearchQueryCreate(BaseModel):
    role_title: str
    location: Optional[str] = "Remoto"
    work_model: Optional[str] = "Remoto"

class JobOpportunityCreate(BaseModel):
    title: str
    company: str
    location: Optional[str] = "Remoto"
    work_model: Optional[str] = "Remoto"
    salary: Optional[str] = None
    link: Optional[str] = None
    description: Optional[str] = None
    skills_required: Optional[str] = None
    notes: Optional[str] = None

class JobOpportunityUpdateStatus(BaseModel):
    status: str
    notes: Optional[str] = None

# --- ROTAS PRINCIPAIS DE TEMPLATES ---

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# --- ROTAS DA API: DASHBOARD & CIDADES ---

@app.get("/api/cities")
def get_cities(db: Session = Depends(get_db)):
    return db.query(models.TargetCity).order_by(models.TargetCity.name).all()

@app.post("/api/cities")
def add_city(city: TargetCityCreate, db: Session = Depends(get_db)):
    clean_name = city.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nome da cidade inválido")

    existing = db.query(models.TargetCity).filter(models.TargetCity.name.ilike(clean_name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cidade já cadastrada")

    new_city = models.TargetCity(name=clean_name, uf=city.uf.upper() if city.uf else "SP")
    db.add(new_city)
    db.commit()
    db.refresh(new_city)
    return new_city

@app.delete("/api/cities/{city_id}")
def delete_city(city_id: int, db: Session = Depends(get_db)):
    city = db.query(models.TargetCity).filter(models.TargetCity.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="Cidade não encontrada")
    db.delete(city)
    db.commit()
    return {"status": "success", "message": "Cidade removida com sucesso"}

# --- ROTAS DA API: CONCURSOS ---

@app.get("/api/concursos")
def get_concursos(city: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Concurso)
    if city:
        query = query.filter(models.Concurso.city.ilike(f"%{city}%"))
    if source:
        query = query.filter(models.Concurso.source == source)
    return query.order_by(models.Concurso.detected_at.desc()).all()

@app.post("/api/concursos/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    result = await run_scraper_job(db)
    return result

# --- ROTAS DA API: TELEGRAM ---

@app.get("/api/telegram")
def get_telegram_settings(db: Session = Depends(get_db)):
    token, chat_id, enabled = get_telegram_config(db)
    return {
        "bot_token": token or "",
        "chat_id": chat_id or "",
        "enabled": enabled,
        "is_configured": bool(token and chat_id)
    }

@app.post("/api/telegram")
def save_telegram_settings(config: TelegramConfigUpdate, db: Session = Depends(get_db)):
    settings = db.query(models.TelegramSettings).first()
    if not settings:
        settings = models.TelegramSettings()
        db.add(settings)

    settings.bot_token = config.bot_token.strip()
    settings.chat_id = config.chat_id.strip()
    settings.enabled = config.enabled
    db.commit()
    db.refresh(settings)
    return {"status": "success", "message": "Configurações do Telegram salvas com sucesso"}

@app.post("/api/telegram/test")
async def test_telegram(db: Session = Depends(get_db)):
    token, chat_id, enabled = get_telegram_config(db)
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Credenciais do Telegram não configuradas.")

    msg = "🚀 <b>Concurso Monitor</b>\n\nTeste de notificação enviado com sucesso! O bot está operando normalmente."
    success = await send_telegram_message(msg, token_override=token, chat_id_override=chat_id)

    if not success:
        raise HTTPException(status_code=500, detail="Falha ao enviar mensagem de teste. Verifique o BOT_TOKEN e CHAT_ID.")

    return {"status": "success", "message": "Mensagem de teste enviada com sucesso no Telegram!"}

# --- ROTAS DA API: EDITAL VERTICALIZADO & ESTUDOS ---

@app.get("/api/positions")
def list_positions(db: Session = Depends(get_db)):
    positions = db.query(models.JobPosition).order_by(models.JobPosition.created_at.desc()).all()
    result = []
    for pos in positions:
        pos_data = {
            "id": pos.id,
            "name": pos.name,
            "target_exam": pos.target_exam,
            "created_at": pos.created_at,
            "subjects": []
        }
        for sub in pos.subjects:
            sub_data = {
                "id": sub.id,
                "name": sub.name,
                "weight": sub.weight,
                "topics": []
            }
            for top in sub.topics:
                sub_data["topics"].append({
                    "id": top.id,
                    "title": top.title,
                    "theory_percent": top.theory_percent,
                    "reviews_count": top.reviews_count,
                    "questions_done": top.questions_done,
                    "questions_correct": top.questions_correct,
                    "accuracy_percent": top.accuracy_percent,
                    "notes": top.notes
                })
            pos_data["subjects"].append(sub_data)
        result.append(pos_data)
    return result

@app.post("/api/positions")
def create_position(pos: JobPositionCreate, db: Session = Depends(get_db)):
    new_pos = models.JobPosition(name=pos.name.strip(), target_exam=pos.target_exam.strip() if pos.target_exam else None)
    db.add(new_pos)
    db.commit()
    db.refresh(new_pos)
    return new_pos

@app.delete("/api/positions/{position_id}")
def delete_position(position_id: int, db: Session = Depends(get_db)):
    pos = db.query(models.JobPosition).filter(models.JobPosition.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Cargo não encontrado")
    db.delete(pos)
    db.commit()
    return {"status": "success"}

@app.post("/api/positions/{position_id}/subjects")
def create_subject(position_id: int, sub: SubjectCreate, db: Session = Depends(get_db)):
    pos = db.query(models.JobPosition).filter(models.JobPosition.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Cargo não encontrado")

    new_sub = models.Subject(position_id=position_id, name=sub.name.strip(), weight=sub.weight or 1.0)
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)
    return new_sub

@app.delete("/api/subjects/{subject_id}")
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    sub = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Disciplina não encontrada")
    db.delete(sub)
    db.commit()
    return {"status": "success"}

@app.post("/api/subjects/{subject_id}/topics")
def create_topic(subject_id: int, top: TopicCreate, db: Session = Depends(get_db)):
    sub = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Disciplina não encontrada")

    new_topic = models.Topic(subject_id=subject_id, title=top.title.strip())
    db.add(new_topic)
    db.commit()
    db.refresh(new_topic)
    return new_topic

@app.put("/api/topics/{topic_id}")
def update_topic(topic_id: int, top_update: TopicUpdate, db: Session = Depends(get_db)):
    topic = db.query(models.Topic).filter(models.Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")

    if top_update.theory_percent is not None:
        topic.theory_percent = min(100, max(0, top_update.theory_percent))
    if top_update.reviews_count is not None:
        topic.reviews_count = max(0, top_update.reviews_count)
    if top_update.questions_done is not None:
        topic.questions_done = max(0, top_update.questions_done)
    if top_update.questions_correct is not None:
        topic.questions_correct = max(0, top_update.questions_correct)
    if top_update.notes is not None:
        topic.notes = top_update.notes

    db.commit()
    db.refresh(topic)
    return {
        "id": topic.id,
        "title": topic.title,
        "theory_percent": topic.theory_percent,
        "reviews_count": topic.reviews_count,
        "questions_done": topic.questions_done,
        "questions_correct": topic.questions_correct,
        "accuracy_percent": topic.accuracy_percent,
        "notes": topic.notes
    }

@app.delete("/api/topics/{topic_id}")
def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = db.query(models.Topic).filter(models.Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")
    db.delete(topic)
    db.commit()
    return {"status": "success"}

# --- HELPER FUNCTION: FIT CALCULATOR ---

def calculate_job_fit_score(skills_required: str, profile: Optional[models.CandidateProfile]) -> float:
    if not profile or not skills_required:
        return 50.0
    
    cand_skills = []
    if profile.primary_skills:
        cand_skills.extend([s.strip().lower() for s in profile.primary_skills.split(",") if s.strip()])
    if profile.secondary_skills:
        cand_skills.extend([s.strip().lower() for s in profile.secondary_skills.split(",") if s.strip()])
    
    if not cand_skills:
        return 50.0

    req_skills = [s.strip().lower() for s in skills_required.split(",") if s.strip()]
    if not req_skills:
        text = skills_required.lower()
        matched = sum(1 for skill in cand_skills if skill in text)
        return min(100.0, round((matched / len(cand_skills)) * 100, 1))

    matches = 0
    for req in req_skills:
        if any(c in req or req in c for c in cand_skills):
            matches += 1

    return min(100.0, round((matches / max(1, len(req_skills))) * 100, 1))

# --- ROTAS DA API: BUSCA DE VAGAS & PERFIL DO CANDIDATO ---

@app.get("/api/job-search/profile")
def get_candidate_profile(db: Session = Depends(get_db)):
    profile = db.query(models.CandidateProfile).first()
    if not profile:
        profile = models.CandidateProfile(
            full_name="",
            headline="",
            location="",
            primary_skills="",
            secondary_skills="",
            experience_summary="",
            target_roles="",
            dealbreakers=""
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile

@app.post("/api/job-search/profile")
def save_candidate_profile(data: CandidateProfileUpdate, db: Session = Depends(get_db)):
    profile = db.query(models.CandidateProfile).first()
    if not profile:
        profile = models.CandidateProfile()
        db.add(profile)

    if data.full_name is not None: profile.full_name = data.full_name.strip()
    if data.headline is not None: profile.headline = data.headline.strip()
    if data.location is not None: profile.location = data.location.strip()
    if data.primary_skills is not None: profile.primary_skills = data.primary_skills.strip()
    if data.secondary_skills is not None: profile.secondary_skills = data.secondary_skills.strip()
    if data.experience_summary is not None: profile.experience_summary = data.experience_summary.strip()
    if data.target_roles is not None: profile.target_roles = data.target_roles.strip()
    if data.dealbreakers is not None: profile.dealbreakers = data.dealbreakers.strip()

    db.commit()
    db.refresh(profile)

    # Recalculate fit score for existing jobs
    jobs = db.query(models.JobOpportunity).all()
    for j in jobs:
        j.fit_score = calculate_job_fit_score(j.skills_required or j.description or "", profile)
    db.commit()

    return profile

@app.get("/api/job-search/queries")
def get_job_queries(db: Session = Depends(get_db)):
    return db.query(models.JobSearchQuery).order_by(models.JobSearchQuery.created_at.desc()).all()

@app.post("/api/job-search/queries")
def create_job_query(query_data: JobSearchQueryCreate, db: Session = Depends(get_db)):
    clean_title = query_data.role_title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Título do cargo é obrigatório")

    new_query = models.JobSearchQuery(
        role_title=clean_title,
        location=query_data.location.strip() if query_data.location else "Remoto",
        work_model=query_data.work_model.strip() if query_data.work_model else "Remoto"
    )
    db.add(new_query)
    db.commit()
    db.refresh(new_query)
    return new_query

@app.delete("/api/job-search/queries/{query_id}")
def delete_job_query(query_id: int, db: Session = Depends(get_db)):
    q = db.query(models.JobSearchQuery).filter(models.JobSearchQuery.id == query_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Filtro não encontrado")
    db.delete(q)
    db.commit()
    return {"status": "success"}

@app.get("/api/job-search/jobs")
def get_job_opportunities(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.JobOpportunity)
    if status and status != "Todas":
        query = query.filter(models.JobOpportunity.status == status)
    return query.order_by(models.JobOpportunity.created_at.desc()).all()

@app.post("/api/job-search/jobs")
def create_job_opportunity(job_data: JobOpportunityCreate, db: Session = Depends(get_db)):
    clean_title = job_data.title.strip()
    clean_company = job_data.company.strip()
    if not clean_title or not clean_company:
        raise HTTPException(status_code=400, detail="Título e Empresa são obrigatórios")

    profile = db.query(models.CandidateProfile).first()
    fit_score = calculate_job_fit_score(job_data.skills_required or job_data.description or "", profile)

    new_job = models.JobOpportunity(
        title=clean_title,
        company=clean_company,
        location=job_data.location.strip() if job_data.location else "Remoto",
        work_model=job_data.work_model.strip() if job_data.work_model else "Remoto",
        salary=job_data.salary.strip() if job_data.salary else None,
        link=job_data.link.strip() if job_data.link else None,
        description=job_data.description.strip() if job_data.description else None,
        skills_required=job_data.skills_required.strip() if job_data.skills_required else None,
        fit_score=fit_score,
        status="Nova",
        notes=job_data.notes.strip() if job_data.notes else None
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job

@app.put("/api/job-search/jobs/{job_id}/status")
def update_job_status(job_id: int, data: JobOpportunityUpdateStatus, db: Session = Depends(get_db)):
    job = db.query(models.JobOpportunity).filter(models.JobOpportunity.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada")

    job.status = data.status
    if data.notes is not None:
        job.notes = data.notes
    db.commit()
    db.refresh(job)
    return job

@app.delete("/api/job-search/jobs/{job_id}")
def delete_job_opportunity(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.JobOpportunity).filter(models.JobOpportunity.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada")
    db.delete(job)
    db.commit()
    return {"status": "success"}

# --- ROTA: SALVAR VAGA DO RESULTADO DE BUSCA NO BOARD ---

@app.post("/api/job-search/jobs/save-from-search")
def save_job_from_search(job_data: JobOpportunityCreate, db: Session = Depends(get_db)):
    """Salva uma vaga encontrada na busca ao vivo diretamente no Board de Candidaturas."""
    # Verificar se a vaga já foi salva (pelo link)
    if job_data.link:
        existing = db.query(models.JobOpportunity).filter(
            models.JobOpportunity.link == job_data.link.strip()
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Vaga já salva no Board de Candidaturas")

    profile = db.query(models.CandidateProfile).first()
    fit_score = calculate_job_fit_score(job_data.skills_required or job_data.description or "", profile)

    new_job = models.JobOpportunity(
        title=job_data.title.strip(),
        company=job_data.company.strip(),
        location=job_data.location.strip() if job_data.location else "Remoto",
        work_model=job_data.work_model.strip() if job_data.work_model else "Remoto",
        salary=job_data.salary.strip() if job_data.salary else None,
        link=job_data.link.strip() if job_data.link else None,
        description=job_data.description.strip() if job_data.description else None,
        skills_required=job_data.skills_required.strip() if job_data.skills_required else None,
        fit_score=fit_score,
        status="Nova",
        notes=job_data.notes.strip() if job_data.notes else None
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job

# --- ROTA: BUSCA AO VIVO DE VAGAS (freehire.dev) ---

class LiveSearchParams(BaseModel):
    country: Optional[str] = None      # ISO-3166 alpha-2, ex: "br", "us", "de" — None = global
    region: Optional[str] = None       # "latam", "eu", "us", "apac", "global"
    work_mode: Optional[str] = None    # "remote", "hybrid", "onsite" — None = qualquer
    jobage: Optional[int] = None       # Vagas dos últimos N dias — None = todas
    limit: Optional[int] = 25

@app.post("/api/job-search/search-live")
async def search_live_jobs(params: LiveSearchParams = None, db: Session = Depends(get_db)):
    if params is None:
        params = LiveSearchParams()
    """
    Busca vagas ao vivo na API pública do freehire.dev usando os filtros
    cadastrados pelo candidato e calcula o Fit Score com base no perfil.
    Endpoint correto: GET /api/v1/jobs/search
    Resposta: { "data": [...], "meta": { "total", "limit", "offset" } }
    """
    profile = db.query(models.CandidateProfile).first()
    queries = db.query(models.JobSearchQuery).filter(models.JobSearchQuery.active == True).all()

    if not queries:
        # Se não há filtros cadastrados, usa cargos alvo do perfil como fallback
        if profile and profile.target_roles:
            role_titles = [r.strip() for r in profile.target_roles.split(",") if r.strip()]
        else:
            raise HTTPException(
                status_code=400,
                detail="Configure pelo menos um filtro de busca na aba 'Filtros & Buscas' antes de pesquisar."
            )
        queries_data = [{"role_title": t, "work_model": "Todos"} for t in role_titles[:3]]
    else:
        queries_data = [{"role_title": q.role_title, "work_model": q.work_model} for q in queries]

    all_results = []
    seen_ids = set()

    freehire_base = "https://freehire.dev"
    search_url = f"{freehire_base}/api/v1/jobs/search"

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ConcursoMonitor/1.0)"
        }
    ) as client:
        for q in queries_data[:5]:  # Máximo 5 filtros por rodada
            try:
                api_params: dict = {
                    "q": q["role_title"],
                    "limit": params.limit or 25,
                    "offset": 0,
                    "semantic_ratio": 0,
                }

                # Filtro de país — prioridade dos params da request, senão usa localização do filtro
                if params.country:
                    api_params["countries"] = params.country.lower()
                elif params.region:
                    api_params["regions"] = params.region.lower()

                # Filtro de modelo de trabalho
                if params.work_mode:
                    api_params["work_mode"] = params.work_mode
                else:
                    work_model_raw = (q.get("work_model") or "").lower()
                    if "remoto" in work_model_raw or work_model_raw == "remote":
                        api_params["work_mode"] = "remote"
                    elif "híbrido" in work_model_raw or "hibrido" in work_model_raw:
                        api_params["work_mode"] = "hybrid"
                    elif "presencial" in work_model_raw or "onsite" in work_model_raw:
                        api_params["work_mode"] = "onsite"
                    # "Todos" = sem filtro de work_mode

                # Filtro de recência
                if params.jobage:
                    api_params["posted_within_days"] = params.jobage

                logger.info(f"freehire.dev search: {search_url} api_params={api_params}")
                resp = await client.get(search_url, params=api_params)
                logger.info(f"freehire.dev response: {resp.status_code} for query='{q['role_title']}'")

                if resp.status_code != 200:
                    logger.warning(f"freehire.dev retornou {resp.status_code}: {resp.text[:200]}")
                    continue

                payload = resp.json()
                results = payload.get("data") or []


                for job in results:
                    # public_slug é o identificador estável (não há "id" numérico exposto)
                    job_id = job.get("public_slug") or job.get("id") or ""
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    # Campos top-level
                    title = (job.get("title") or "").strip()
                    if not title:
                        continue

                    # company é string direta (não objeto)
                    company = (job.get("company") or "").strip() or "Empresa não informada"
                    job_url = job.get("url") or f"{freehire_base}/jobs/{job_id}"

                    # Skills (lista de strings)
                    skills_list = job.get("skills") or []
                    skills_str = ", ".join(skills_list) if isinstance(skills_list, list) else ""

                    # Description (HTML — limpamos o básico)
                    raw_desc = job.get("description") or ""
                    import re as _re
                    clean_desc = _re.sub(r'<[^>]+>', ' ', raw_desc).strip()
                    clean_desc = _re.sub(r'\s+', ' ', clean_desc)[:500]

                    # Enrichment (seniority, category, salary ficam aqui)
                    enrichment = job.get("enrichment") or {}
                    seniority = enrichment.get("seniority") or ""
                    salary_min = enrichment.get("salary_min")
                    salary_max = enrichment.get("salary_max")
                    salary_currency = enrichment.get("salary_currency") or ""
                    if salary_min and salary_max:
                        salary_str = f"{salary_currency} {salary_min:,}–{salary_max:,}".strip()
                    elif salary_min:
                        salary_str = f"{salary_currency} {salary_min:,}+".strip()
                    else:
                        salary_str = ""

                    # Localização — location é campo de texto livre do ATS
                    location_raw = (job.get("location") or "").strip()
                    regions = job.get("regions") or []
                    countries = job.get("countries") or []
                    cities = job.get("cities") or []
                    if location_raw:
                        location = location_raw
                    else:
                        parts = cities[:1] + countries[:1] + regions[:1]
                        location = ", ".join(parts) if parts else "Remoto/Global"

                    # Modelo de trabalho
                    raw_wm = (job.get("work_mode") or "").lower()
                    if raw_wm == "remote":
                        wm = "Remoto"
                    elif raw_wm == "hybrid":
                        wm = "Híbrido"
                    elif raw_wm == "onsite":
                        wm = "Presencial"
                    else:
                        wm = "Não informado"

                    # Fit Score (usa skills + description)
                    fit_text = skills_str if skills_str else clean_desc
                    fit = calculate_job_fit_score(fit_text, profile)

                    # Data de publicação
                    posted_at = job.get("posted_at") or ""

                    all_results.append({
                        "id": job_id,
                        "title": title,
                        "company": company,
                        "location": location,
                        "work_model": wm,
                        "salary": salary_str or None,
                        "link": job_url,
                        "skills_required": skills_str,
                        "description": clean_desc,
                        "fit_score": fit,
                        "posted_at": posted_at,
                        "source": "freehire.dev",
                        "seniority": seniority,
                        "query_used": q["role_title"],
                    })

            except Exception as e:
                logger.error(f"Erro ao buscar no freehire.dev para '{q['role_title']}': {e}", exc_info=True)
                continue

    # Ordenar por fit_score decrescente
    all_results.sort(key=lambda x: x["fit_score"], reverse=True)

    return {
        "status": "success",
        "total": len(all_results),
        "results": all_results
    }

# --- ROTAS DA API: STATS DASHBOARD ---


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    cities_count = db.query(models.TargetCity).filter(models.TargetCity.active == True).count()
    concursos_count = db.query(models.Concurso).count()

    topics = db.query(models.Topic).all()
    total_topics = len(topics)
    avg_theory = round(sum([t.theory_percent for t in topics]) / total_topics, 1) if total_topics > 0 else 0.0

    total_q_done = sum([t.questions_done for t in topics])
    total_q_correct = sum([t.questions_correct for t in topics])
    avg_accuracy = round((total_q_correct / total_q_done) * 100, 1) if total_q_done > 0 else 0.0

    jobs_count = db.query(models.JobOpportunity).count()
    applied_count = db.query(models.JobOpportunity).filter(models.JobOpportunity.status == "Aplicado").count()

    return {
        "cities_count": cities_count,
        "concursos_count": concursos_count,
        "total_topics": total_topics,
        "avg_theory": avg_theory,
        "total_questions": total_q_done,
        "avg_accuracy": avg_accuracy,
        "jobs_count": jobs_count,
        "applied_count": applied_count
    }

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import httpx
from app import job_search as js
from app import finance

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

class TransactionCreate(BaseModel):
    date: str
    title: str
    amount: float
    category: Optional[str] = "Outros"
    payment_method: Optional[str] = "Cartão Nubank"
    notes: Optional[str] = None

class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    title: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None

class PasteImportRequest(BaseModel):
    content: str
    default_payment_method: Optional[str] = "Cartão Nubank"

class CategoryRuleCreate(BaseModel):
    keyword: str
    category_name: str

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

# --- ROTA: BUSCA INTELIGENTE DE VAGAS (Multi-fonte: LinkedIn + Gupy + freehire.dev) ---

class SmartSearchParams(BaseModel):
    prompt: Optional[str] = None       # Texto livre do usuário
    work_mode: Optional[str] = None    # "remote", "hybrid", "onsite" — None = qualquer
    jobage: Optional[int] = None       # Vagas dos últimos N dias — None = todas
    location: Optional[str] = "Brasil" # Localização para LinkedIn

@app.get("/api/job-search/smart-terms")
def get_smart_terms(db: Session = Depends(get_db)):
    """Retorna os termos de busca derivados automaticamente do perfil cadastrado."""
    profile = db.query(models.CandidateProfile).first()
    if not profile:
        return {"terms": [], "message": "Perfil não encontrado. Cadastre seu perfil primeiro."}
    terms = js.derive_search_terms(
        headline=profile.headline or "",
        primary_skills=profile.primary_skills or "",
        secondary_skills=profile.secondary_skills or "",
        target_roles=profile.target_roles or "",
        experience_summary=profile.experience_summary or "",
    )
    return {"terms": terms}

@app.post("/api/job-search/smart-search")
async def smart_search_jobs(params: SmartSearchParams = None, db: Session = Depends(get_db)):
    """
    Busca inteligente multi-fonte: LinkedIn + Gupy + freehire.dev
    Deriva os termos de busca automaticamente do perfil cadastrado.
    Aceita prompt em linguagem natural para refinar a busca.
    """
    if params is None:
        params = SmartSearchParams()

    profile = db.query(models.CandidateProfile).first()

    # Derivar termos de busca do perfil + prompt
    terms = js.derive_search_terms(
        headline=profile.headline or "" if profile else "",
        primary_skills=profile.primary_skills or "" if profile else "",
        secondary_skills=profile.secondary_skills or "" if profile else "",
        target_roles=profile.target_roles or "" if profile else "",
        experience_summary=profile.experience_summary or "" if profile else "",
        prompt=params.prompt or "",
    )

    if not terms:
        raise HTTPException(
            status_code=400,
            detail="Não foi possível derivar termos de busca. Preencha seu perfil (Headline, Habilidades ou Cargos Desejados) ou digite um prompt."
        )

    logger.info(f"Smart search — termos derivados: {terms}")

    # Habilidades e cargos-alvo do candidato para cálculo do Fit Score
    cand_skills: list[str] = []
    target_roles: list[str] = []
    if profile:
        if profile.primary_skills:
            cand_skills += [s.strip() for s in profile.primary_skills.split(",") if s.strip()]
        if profile.secondary_skills:
            cand_skills += [s.strip() for s in profile.secondary_skills.split(",") if s.strip()]
        if profile.target_roles:
            target_roles = [r.strip() for r in profile.target_roles.split(",") if r.strip()]

    all_results: list[dict] = []
    seen_ids: set[str] = set()
    location = params.location or "Brasil"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        # Executar buscas em paralelo para cada termo
        for term in terms[:4]:  # Máx 4 termos por rodada
            tasks = [
                js.search_linkedin_br(client, term, location=location,
                                      work_mode=params.work_mode, jobage=params.jobage),
                js.search_gupy_br(client, term),
                js.search_freehire_br(client, term, work_mode=params.work_mode, jobage=params.jobage),
            ]
            batch = await asyncio.gather(*tasks, return_exceptions=True)

            for result_list in batch:
                if isinstance(result_list, Exception):
                    logger.error(f"Erro em batch de busca: {result_list}")
                    continue
                for job in (result_list or []):
                    job_id = job.get("id", "")
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    # Calcular Fit Score
                    job["fit_score"] = js.compute_fit_score(job, cand_skills, target_roles)
                    all_results.append(job)

    # Ordenar por fit_score decrescente, depois por fonte (LinkedIn primeiro)
    source_order = {"LinkedIn": 0, "Gupy": 1, "freehire.dev": 2}
    all_results.sort(key=lambda x: (-x["fit_score"], source_order.get(x.get("source", ""), 9)))

    return {
        "status": "success",
        "terms_used": terms,
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

    finances_count = db.query(models.FinanceTransaction).count()
    finances_total_spent = sum([t.amount for t in db.query(models.FinanceTransaction.amount).all()])

    return {
        "cities_count": cities_count,
        "concursos_count": concursos_count,
        "total_topics": total_topics,
        "avg_theory": avg_theory,
        "total_questions": total_q_done,
        "avg_accuracy": avg_accuracy,
        "jobs_count": jobs_count,
        "applied_count": applied_count,
        "finances_count": finances_count,
        "finances_total_spent": round(finances_total_spent, 2)
    }

# --- ROTAS DA API: ANÁLISE FINANCEIRA (NUBANK & GASTOS) ---

@app.get("/api/finances/summary")
def get_finance_summary(month: Optional[str] = None, db: Session = Depends(get_db)):
    """Retorna métricas consolidadas, dados para gráficos e distribuição por categoria."""
    all_transactions = db.query(models.FinanceTransaction).all()
    
    # Calcular resumo geral de todos os meses
    global_summary = finance.compute_financial_summary(all_transactions)
    
    # Se um mês específico foi filtrado, calcular resumo focado nele
    if month and month != "Todos":
        filtered_transactions = [t for t in all_transactions if t.month_year == month]
        month_summary = finance.compute_financial_summary(filtered_transactions)
        
        return {
            "selected_month": month,
            "total_spent": month_summary["total_spent"],
            "total_transactions": month_summary["total_transactions"],
            "avg_monthly": global_summary["avg_monthly"],
            "top_category": month_summary["top_category"],
            "top_category_amount": month_summary["top_category_amount"],
            "top_category_percent": month_summary["top_category_percent"],
            "available_months": global_summary["available_months"],
            "categories_breakdown": month_summary["categories_breakdown"],
            "monthly_breakdown": global_summary["monthly_breakdown"], # Mantém o histórico completo para o gráfico de linha/barra
        }
    
    return {
        "selected_month": "Todos",
        "total_spent": global_summary["total_spent"],
        "total_transactions": global_summary["total_transactions"],
        "avg_monthly": global_summary["avg_monthly"],
        "top_category": global_summary["top_category"],
        "top_category_amount": global_summary["top_category_amount"],
        "top_category_percent": global_summary["top_category_percent"],
        "available_months": global_summary["available_months"],
        "categories_breakdown": global_summary["categories_breakdown"],
        "monthly_breakdown": global_summary["monthly_breakdown"],
    }

@app.get("/api/finances/transactions")
def get_finance_transactions(
    month: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lista as transações financeiras com suporte a filtros por mês, categoria e busca textual."""
    query = db.query(models.FinanceTransaction)
    
    if month and month != "Todos":
        query = query.filter(models.FinanceTransaction.month_year == month)
    if category and category != "Todas":
        query = query.filter(models.FinanceTransaction.category == category)
    if search:
        search_clean = search.strip()
        query = query.filter(models.FinanceTransaction.title.ilike(f"%{search_clean}%"))

    return query.order_by(models.FinanceTransaction.date.desc(), models.FinanceTransaction.id.desc()).all()

@app.post("/api/finances/transactions")
def create_finance_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    """Adiciona manualmente um gasto/transação."""
    clean_title = data.title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Título do lançamento é obrigatório")

    dt_obj, month_year = finance.parse_date_str(data.date)
    
    # Categorização inteligente se não especificada ou deixada como Outros
    category = data.category.strip() if data.category else "Outros"
    if category in ["Outros", ""]:
        rules = db.query(models.FinanceCategoryRule).all()
        rule_dicts = [{"keyword": r.keyword, "category_name": r.category_name} for r in rules]
        category = finance.categorize_transaction(clean_title, None, rule_dicts)

    new_tx = models.FinanceTransaction(
        date=dt_obj,
        month_year=month_year,
        title=clean_title,
        amount=finance.parse_amount(data.amount),
        category=category,
        payment_method=data.payment_method.strip() if data.payment_method else "Cartão Nubank",
        notes=data.notes.strip() if data.notes else None
    )
    db.add(new_tx)
    db.commit()
    db.refresh(new_tx)
    return new_tx

@app.put("/api/finances/transactions/{tx_id}")
def update_finance_transaction(tx_id: int, data: TransactionUpdate, db: Session = Depends(get_db)):
    """Atualiza dados de uma transação (como categoria, valor ou notas)."""
    tx = db.query(models.FinanceTransaction).filter(models.FinanceTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    if data.title is not None:
        tx.title = data.title.strip()
    if data.amount is not None:
        tx.amount = finance.parse_amount(data.amount)
    if data.category is not None:
        tx.category = data.category.strip()
    if data.payment_method is not None:
        tx.payment_method = data.payment_method.strip()
    if data.notes is not None:
        tx.notes = data.notes.strip()
    if data.date is not None:
        dt_obj, month_year = finance.parse_date_str(data.date)
        tx.date = dt_obj
        tx.month_year = month_year

    db.commit()
    db.refresh(tx)
    return tx

@app.delete("/api/finances/transactions/{tx_id}")
def delete_finance_transaction(tx_id: int, db: Session = Depends(get_db)):
    """Remove uma transação individual."""
    tx = db.query(models.FinanceTransaction).filter(models.FinanceTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")
    db.delete(tx)
    db.commit()
    return {"status": "success", "message": "Lançamento excluído com sucesso"}

@app.post("/api/finances/upload")
async def upload_finance_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Importa faturas a partir do upload de arquivos CSV, OFX ou TXT do Nubank."""
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1", errors="ignore")

    rules = db.query(models.FinanceCategoryRule).all()
    rule_dicts = [{"keyword": r.keyword, "category_name": r.category_name} for r in rules]

    filename_lower = file.filename.lower() if file.filename else ""
    
    if filename_lower.endswith(".ofx") or "<OFX>" in content or "<STMTTRN>" in content:
        parsed_items = finance.parse_ofx(content, rule_dicts)
    else:
        parsed_items = finance.parse_nubank_csv(content, rule_dicts)
        if not parsed_items:
            parsed_items = finance.parse_raw_text(content, rule_dicts)

    if not parsed_items:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma transação válida foi encontrada no arquivo. Certifique-se de que é uma fatura CSV/OFX do Nubank."
        )

    db_items = []
    for item in parsed_items:
        new_tx = models.FinanceTransaction(
            date=item["date"],
            month_year=item["month_year"],
            title=item["title"],
            amount=item["amount"],
            category=item["category"],
            original_category=item.get("original_category"),
            payment_method=item.get("payment_method", "Cartão Nubank")
        )
        db.add(new_tx)
        db_items.append(new_tx)

    db.commit()

    total_amt = round(sum([i["amount"] for i in parsed_items]), 2)
    return {
        "status": "success",
        "imported_count": len(parsed_items),
        "total_amount": total_amt,
        "message": f"{len(parsed_items)} lançamentos importados com sucesso (Total: R$ {total_amt:,.2f})!"
    }

@app.post("/api/finances/paste")
def paste_finance_text(data: PasteImportRequest, db: Session = Depends(get_db)):
    """Importa faturas a partir de texto bruto colado pelo usuário."""
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Texto da fatura não pode estar vazio")

    rules = db.query(models.FinanceCategoryRule).all()
    rule_dicts = [{"keyword": r.keyword, "category_name": r.category_name} for r in rules]

    parsed_items = finance.parse_raw_text(data.content, rule_dicts)
    if not parsed_items:
        raise HTTPException(status_code=400, detail="Não foi possível identificar lançamentos no texto colado.")

    for item in parsed_items:
        new_tx = models.FinanceTransaction(
            date=item["date"],
            month_year=item["month_year"],
            title=item["title"],
            amount=item["amount"],
            category=item["category"],
            original_category=item.get("original_category"),
            payment_method=data.default_payment_method or "Cartão Nubank"
        )
        db.add(new_tx)

    db.commit()

    total_amt = round(sum([i["amount"] for i in parsed_items]), 2)
    return {
        "status": "success",
        "imported_count": len(parsed_items),
        "total_amount": total_amt,
        "message": f"{len(parsed_items)} lançamentos importados com sucesso!"
    }

@app.delete("/api/finances/clear")
def clear_finances(month: Optional[str] = None, db: Session = Depends(get_db)):
    """Limpa lançamentos financeiros (todos ou apenas de um mês selecionado)."""
    query = db.query(models.FinanceTransaction)
    if month and month != "Todos":
        deleted_count = query.filter(models.FinanceTransaction.month_year == month).delete()
        msg = f"Lançamentos do mês {month} apagados com sucesso ({deleted_count} itens)."
    else:
        deleted_count = query.delete()
        msg = f"Todos os lançamentos financeiros foram apagados com sucesso ({deleted_count} itens)."

    db.commit()
    return {"status": "success", "deleted_count": deleted_count, "message": msg}

@app.get("/api/finances/rules")
def get_finance_rules(db: Session = Depends(get_db)):
    """Lista todas as regras de autocategorização customizadas."""
    return db.query(models.FinanceCategoryRule).order_by(models.FinanceCategoryRule.keyword).all()

@app.post("/api/finances/rules")
def add_finance_rule(rule_data: CategoryRuleCreate, recategorize_existing: bool = True, db: Session = Depends(get_db)):
    """Adiciona uma nova regra de categorização por palavra-chave."""
    clean_kw = rule_data.keyword.strip()
    clean_cat = rule_data.category_name.strip()

    if not clean_kw or not clean_cat:
        raise HTTPException(status_code=400, detail="Palavra-chave e categoria são obrigatórias")

    existing = db.query(models.FinanceCategoryRule).filter(models.FinanceCategoryRule.keyword.ilike(clean_kw)).first()
    if existing:
        existing.category_name = clean_cat
        rule = existing
    else:
        rule = models.FinanceCategoryRule(keyword=clean_kw, category_name=clean_cat)
        db.add(rule)

    db.commit()
    db.refresh(rule)

    # Reaplicar a transações existentes se solicitado
    updated_count = 0
    if recategorize_existing:
        all_tx = db.query(models.FinanceTransaction).all()
        rules = db.query(models.FinanceCategoryRule).all()
        rule_dicts = [{"keyword": r.keyword, "category_name": r.category_name} for r in rules]
        for tx in all_tx:
            new_cat = finance.categorize_transaction(tx.title, tx.original_category, rule_dicts)
            if new_cat != tx.category:
                tx.category = new_cat
                updated_count += 1
        db.commit()

    return {
        "status": "success",
        "rule": rule,
        "updated_transactions_count": updated_count,
        "message": f"Regra cadastrada! {updated_count} transações foram recategorizadas."
    }

@app.delete("/api/finances/rules/{rule_id}")
def delete_finance_rule(rule_id: int, db: Session = Depends(get_db)):
    """Remove uma regra de categorização."""
    rule = db.query(models.FinanceCategoryRule).filter(models.FinanceCategoryRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regra não encontrada")
    db.delete(rule)
    db.commit()
    return {"status": "success", "message": "Regra removida com sucesso"}


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

from datetime import datetime
import httpx
from app import job_search as js
from app import finance
from app import taxonomy
from app import deduplication

from app.database import Base, engine, get_db, SessionLocal
from app import models
from app.scraper import run_scraper_job
from app.telegram import send_telegram_message, get_telegram_config, notify_new_jobs


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

async def scheduled_job_search():
    """Varredura periódica de vagas multi-plataforma e alerta de novas oportunidades no Telegram."""
    db = SessionLocal()
    try:
        logger.info("Executando busca agendada automática de vagas...")
        profile = db.query(models.CandidateProfile).first()
        primary_role = "Analista de Suporte"
        cand_skills = []
        target_roles = []
        if profile:
            if profile.target_roles:
                primary_role = profile.target_roles.split(",")[0].strip()
                target_roles = [r.strip() for r in profile.target_roles.split(",") if r.strip()]
            if profile.primary_skills:
                cand_skills = [s.strip() for s in profile.primary_skills.split(",") if s.strip()]

        terms = taxonomy.expand_search_terms(primary_role)
        results = await js.run_multi_platform_search(terms, location="Brasil", max_per_platform=10)

        existing_jobs = db.query(models.JobOpportunity).all()
        new_jobs = []

        for raw in results:
            is_dup, matched_job = deduplication.is_duplicate(raw, existing_jobs)
            if is_dup and matched_job:
                matched_job.other_sources = deduplication.merge_job_sources(
                    matched_job.other_sources, raw.get("source", "Outra"), raw.get("link", "")
                )
                if not matched_job.salary and raw.get("salary"):
                    matched_job.salary = raw.get("salary")
                if matched_job.pcd_type == "Ampla" and raw.get("pcd_type") != "Ampla":
                    matched_job.pcd_type = raw.get("pcd_type")
            elif not is_dup:
                fit = js.compute_fit_score(raw, cand_skills, target_roles)
                new_job = models.JobOpportunity(
                    title=raw["title"],
                    company=raw["company"],
                    location=raw.get("location") or "Brasil",
                    work_model=raw.get("work_model") or "Remoto",
                    salary=raw.get("salary"),
                    link=raw.get("link"),
                    description=raw.get("description"),
                    skills_required=raw.get("skills_required"),
                    fit_score=fit,
                    status="Nova",
                    is_viewed=False,
                    user_interest="Pendente",
                    is_open=raw.get("is_open", True),
                    application_deadline=raw.get("application_deadline"),
                    pcd_type=raw.get("pcd_type", "Ampla"),
                    primary_source=raw.get("source", "Gupy"),
                    other_sources=raw.get("other_sources"),
                    dedup_hash=raw.get("dedup_hash")
                )
                db.add(new_job)
                db.commit()
                db.refresh(new_job)
                existing_jobs.append(new_job)
                new_jobs.append(new_job)

        db.commit()
        if new_jobs:
            logger.info(f"{len(new_jobs)} novas vagas inseridas na busca agendada. Notificando Telegram...")
            await notify_new_jobs(new_jobs[:8], db)
    except Exception as e:
        logger.error(f"Erro no agendador de vagas: {e}")
    finally:
        db.close()


def check_and_migrate_db():
    """Migração leve para SQLite garantindo colunas adicionadas recentemente."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            # Migração finance_transactions
            res_fin = conn.execute(text("PRAGMA table_info(finance_transactions)"))
            columns_fin = [row[1] for row in res_fin.fetchall()]
            if columns_fin and "transaction_type" not in columns_fin:
                conn.execute(text("ALTER TABLE finance_transactions ADD COLUMN transaction_type VARCHAR(20) DEFAULT 'expense'"))
                conn.commit()
                logger.info("Migração: coluna 'transaction_type' adicionada em finance_transactions.")

            # Migração job_opportunities
            res_jobs = conn.execute(text("PRAGMA table_info(job_opportunities)"))
            columns_jobs = [row[1] for row in res_jobs.fetchall()]
            if columns_jobs:
                needed_cols = [
                    ("is_viewed", "BOOLEAN DEFAULT 0"),
                    ("viewed_at", "DATETIME"),
                    ("user_interest", "VARCHAR(50) DEFAULT 'Pendente'"),
                    ("is_open", "BOOLEAN DEFAULT 1"),
                    ("application_deadline", "VARCHAR(100)"),
                    ("pcd_type", "VARCHAR(30) DEFAULT 'Ampla'"),
                    ("primary_source", "VARCHAR(50) DEFAULT 'Gupy'"),
                    ("other_sources", "TEXT"),
                    ("dedup_hash", "VARCHAR(64)"),
                    ("last_checked_at", "DATETIME")
                ]
                for col_name, col_def in needed_cols:
                    if col_name not in columns_jobs:
                        conn.execute(text(f"ALTER TABLE job_opportunities ADD COLUMN {col_name} {col_def}"))
                        conn.commit()
                        logger.info(f"Migração: coluna '{col_name}' adicionada em job_opportunities.")
    except Exception as ex:
        logger.warning(f"Aviso na verificação de migração do banco: {ex}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Criar tabelas se não existirem
    Base.metadata.create_all(bind=engine)
    check_and_migrate_db()

    # Configurar agendamento diário de concursos (padrão 07:00 AM)
    hour = int(os.getenv("SCRAPER_CRON_HOUR", "7"))
    minute = int(os.getenv("SCRAPER_CRON_MINUTE", "0"))
    scheduler.add_job(
        scheduled_scraper,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_concurso_scraper",
        replace_existing=True
    )

    # Configurar agendamento diário de vagas (padrão 08:30 AM)
    job_hour = int(os.getenv("JOB_SEARCH_CRON_HOUR", "8"))
    job_minute = int(os.getenv("JOB_SEARCH_CRON_MINUTE", "30"))
    scheduler.add_job(
        scheduled_job_search,
        trigger=CronTrigger(hour=job_hour, minute=job_minute),
        id="daily_job_search",
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"APScheduler iniciado: concursos às {hour:02d}:{minute:02d}, vagas às {job_hour:02d}:{job_minute:02d}.")


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
    pcd_type: Optional[str] = "Ampla"
    is_open: Optional[bool] = True
    notes: Optional[str] = None

class JobOpportunityUpdateStatus(BaseModel):
    status: str
    notes: Optional[str] = None

class JobViewedUpdate(BaseModel):
    is_viewed: bool

class JobInterestUpdate(BaseModel):
    interest: str

class JobRunSearchParams(BaseModel):
    primary_term: str = "Analista de Suporte"
    selected_adjacents: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    location: Optional[str] = "Brasil"
    work_mode: Optional[str] = None
    work_model: Optional[str] = None
    jobage: Optional[int] = None
    notify_telegram: Optional[bool] = False
    auto_save: Optional[bool] = True


class TransactionCreate(BaseModel):
    date: str
    title: str
    amount: float
    transaction_type: Optional[str] = "expense"
    category: Optional[str] = "Outros"
    payment_method: Optional[str] = "Cartão Nubank"
    notes: Optional[str] = None

class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    title: Optional[str] = None
    amount: Optional[float] = None
    transaction_type: Optional[str] = None
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
def get_job_opportunities(
    status: Optional[str] = None,
    viewed: Optional[bool] = None,
    interest: Optional[str] = None,
    pcd: Optional[str] = None,
    is_open: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retorna as vagas da base de dados com suporte a filtros completos:
    - status da candidatura
    - visualizada (já vi ou não)
    - interesse pessoal (Pendente, Interesse, Sem Interesse, Aplicado)
    - política PCD (Ampla, Afirmativa PCD, Exclusiva PCD, PCD Geral)
    - status da vaga (Em Aberto ou Encerrada)
    - busca por termo
    """
    query = db.query(models.JobOpportunity)

    if status and status != "Todas":
        query = query.filter(models.JobOpportunity.status == status)

    if viewed is not None:
        query = query.filter(models.JobOpportunity.is_viewed == viewed)

    if interest and interest != "Todas":
        query = query.filter(models.JobOpportunity.user_interest == interest)

    if pcd and pcd != "Todas":
        if pcd == "PCD Geral":
            query = query.filter(models.JobOpportunity.pcd_type.in_(["Afirmativa PCD", "Exclusiva PCD"]))
        else:
            query = query.filter(models.JobOpportunity.pcd_type == pcd)

    if is_open is not None:
        query = query.filter(models.JobOpportunity.is_open == is_open)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            (models.JobOpportunity.title.ilike(term)) |
            (models.JobOpportunity.company.ilike(term)) |
            (models.JobOpportunity.location.ilike(term))
        )

    return query.order_by(models.JobOpportunity.created_at.desc()).all()

@app.post("/api/job-search/jobs")
def create_job_opportunity(job_data: JobOpportunityCreate, db: Session = Depends(get_db)):
    clean_title = job_data.title.strip()
    clean_company = job_data.company.strip()
    if not clean_title or not clean_company:
        raise HTTPException(status_code=400, detail="Título e Empresa são obrigatórios")

    profile = db.query(models.CandidateProfile).first()
    fit_score = calculate_job_fit_score(job_data.skills_required or job_data.description or "", profile)

    detected_pcd = js.detect_pcd_type(clean_title, job_data.description or "")
    final_pcd = job_data.pcd_type if (job_data.pcd_type and job_data.pcd_type != "Ampla") else detected_pcd
    dedup_hash = deduplication.generate_dedup_hash(clean_company, clean_title, job_data.location or "")

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
        is_viewed=False,
        user_interest="Pendente",
        is_open=True if job_data.is_open is None else job_data.is_open,
        pcd_type=final_pcd,
        primary_source="Manual",
        dedup_hash=dedup_hash,
        notes=job_data.notes.strip() if job_data.notes else None
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job

@app.put("/api/job-search/jobs/{job_id}/viewed")
def update_job_viewed(job_id: int, data: JobViewedUpdate, db: Session = Depends(get_db)):
    """Atualiza o status de 'já visto' ou 'não visto' da vaga."""
    job = db.query(models.JobOpportunity).filter(models.JobOpportunity.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada")
    job.is_viewed = data.is_viewed
    job.viewed_at = datetime.utcnow() if data.is_viewed else None
    db.commit()
    db.refresh(job)
    return {"status": "success", "id": job.id, "is_viewed": job.is_viewed}

@app.put("/api/job-search/jobs/{job_id}/interest")
def update_job_interest(job_id: int, data: JobInterestUpdate, db: Session = Depends(get_db)):
    """Atualiza o nível de interesse pessoal na vaga (Pendente, Interesse, Sem Interesse, Aplicado)."""
    job = db.query(models.JobOpportunity).filter(models.JobOpportunity.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada")
    job.user_interest = data.interest
    # Se marcou interesse ou aplicou, marca automaticamente como vista
    if data.interest in ("Interesse", "Aplicado", "Sem Interesse"):
        job.is_viewed = True
        if not job.viewed_at:
            job.viewed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return {"status": "success", "id": job.id, "user_interest": job.user_interest, "is_viewed": job.is_viewed}

@app.post("/api/job-search/jobs/mark-all-viewed")
def mark_all_jobs_viewed(db: Session = Depends(get_db)):
    """Marca todas as vagas da base como visualizadas."""
    now = datetime.utcnow()
    db.query(models.JobOpportunity).filter(models.JobOpportunity.is_viewed == False).update({
        models.JobOpportunity.is_viewed: True,
        models.JobOpportunity.viewed_at: now
    })
    db.commit()
    return {"status": "success", "message": "Todas as vagas foram marcadas como visualizadas."}

@app.post("/api/job-search/jobs/{job_id}/check-status")
async def check_single_job_status(job_id: int, db: Session = Depends(get_db)):
    """Checa se o link da vaga ainda está ativo e se a inscrição continua em aberto."""
    job = db.query(models.JobOpportunity).filter(models.JobOpportunity.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada")

    if not job.link:
        return {"status": "ok", "is_open": job.is_open, "message": "Sem link para checagem"}

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(job.link, headers=js.BROWSER_HEADERS)
            if resp.status_code in (404, 410):
                job.is_open = False
            else:
                is_open, _ = js.detect_open_status(job.application_deadline, resp.text)
                job.is_open = is_open
            job.last_checked_at = datetime.utcnow()
            db.commit()
            db.refresh(job)
            return {"status": "success", "id": job.id, "is_open": job.is_open}
    except Exception as e:
        logger.warning(f"Erro ao verificar link da vaga {job_id}: {e}")
        return {"status": "error", "id": job.id, "is_open": job.is_open, "message": str(e)}

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

# --- ROTAS: TAXONOMIA E TERMOS ADJACENTES ---

@app.get("/api/job-search/taxonomy")
def get_job_taxonomy():
    """Retorna as categorias estruturadas e termos para sugestões rápidas."""
    return {
        "categories": taxonomy.get_taxonomy_overview(),
        "available_platforms": [
            {"key": k, "name": v[0]} for k, v in js.AVAILABLE_PLATFORMS.items()
        ]
    }

@app.get("/api/job-search/adjacent-terms")
def get_adjacent_terms(term: str = "Analista de Suporte"):
    """Retorna os termos de busca adjacentes/referências para um termo principal."""
    adjacents = taxonomy.find_adjacent_terms(term)
    return {"primary_term": term, "adjacent_terms": adjacents}

# --- ROTA: MOTOR DE BUSCA MULTI-PLATAFORMA E DEDUPLICAÇÃO ---

@app.post("/api/job-search/run-search")
async def run_job_search(params: JobRunSearchParams, db: Session = Depends(get_db)):
    """
    Executa varredura nas 10 plataformas de recrutamento.
    Aplica expansão semântica de termos, deduplicação cross-plataforma e salva na base de dados.
    """
    primary = params.primary_term.strip() or "Analista de Suporte"
    selected_adjacents = params.selected_adjacents or []
    
    # Se o usuário selecionou termos adjacentes, pesquisa o principal + selecionados (máximo 4 termos)
    if selected_adjacents:
        queries = [primary] + [a for a in selected_adjacents if a != primary][:3]
    else:
        queries = [primary]
        
    effective_work_mode = params.work_mode or params.work_model
    logger.info(f"Busca multi-plataforma iniciada para: {queries} nas plataformas: {params.platforms} (modalidade: {effective_work_mode})")

    # Executar busca nas plataformas selecionadas
    try:
        raw_results = await js.run_multi_platform_search(
            queries=queries,
            selected_platform_keys=params.platforms,
            location=params.location or "Brasil",
            work_mode=effective_work_mode,
            jobage=params.jobage,
            max_per_platform=12
        )
    except Exception as e:
        logger.error(f"Erro durante execução da busca multi-plataforma: {e}", exc_info=True)
        raw_results = []

    profile = db.query(models.CandidateProfile).first()
    cand_skills = [s.strip() for s in profile.primary_skills.split(",") if s.strip()] if (profile and profile.primary_skills) else []
    target_roles = [r.strip() for r in profile.target_roles.split(",") if r.strip()] if (profile and profile.target_roles) else [primary]

    existing_jobs = db.query(models.JobOpportunity).all()
    newly_added: List[models.JobOpportunity] = []
    merged_count = 0

    if params.auto_save:
        for raw in raw_results:
            is_dup, matched_job = deduplication.is_duplicate(raw, existing_jobs)
            if is_dup and matched_job:
                # Atualiza fontes alternativas
                matched_job.other_sources = deduplication.merge_job_sources(
                    matched_job.other_sources, raw.get("source", "Outra"), raw.get("link", "")
                )
                if not matched_job.salary and raw.get("salary"):
                    matched_job.salary = raw.get("salary")
                if matched_job.pcd_type == "Ampla" and raw.get("pcd_type") != "Ampla":
                    matched_job.pcd_type = raw.get("pcd_type")
                if not matched_job.application_deadline and raw.get("application_deadline"):
                    matched_job.application_deadline = raw.get("application_deadline")
                merged_count += 1
            elif not is_dup:
                fit = js.compute_fit_score(raw, cand_skills, target_roles)
                new_job = models.JobOpportunity(
                    title=raw["title"],
                    company=raw["company"],
                    location=raw.get("location") or "Brasil",
                    work_model=raw.get("work_model") or "Remoto",
                    salary=raw.get("salary"),
                    link=raw.get("link"),
                    description=raw.get("description"),
                    skills_required=raw.get("skills_required"),
                    fit_score=fit,
                    status="Nova",
                    is_viewed=False,
                    user_interest="Pendente",
                    is_open=raw.get("is_open", True),
                    application_deadline=raw.get("application_deadline"),
                    pcd_type=raw.get("pcd_type", "Ampla"),
                    primary_source=raw.get("source", "Gupy"),
                    other_sources=raw.get("other_sources"),
                    dedup_hash=raw.get("dedup_hash")
                )
                db.add(new_job)
                db.commit()
                db.refresh(new_job)
                existing_jobs.append(new_job)
                newly_added.append(new_job)

        db.commit()

        # Notificar via Telegram se requisitado e houver vagas inéditas
        if params.notify_telegram and newly_added:
            await notify_new_jobs(newly_added[:8], db)

    return {
        "status": "success",
        "primary_term": primary,
        "terms_used": queries,
        "total_found": len(raw_results),
        "newly_added_count": len(newly_added),
        "merged_duplicates_count": merged_count,
        "results": raw_results
    }

# Compatibilidade retroativa com endpoint smart-search
class SmartSearchParams(BaseModel):
    prompt: Optional[str] = None
    location: Optional[str] = "Brasil"
    work_mode: Optional[str] = None
    jobage: Optional[int] = None

@app.post("/api/job-search/smart-search")
async def smart_search_jobs_compat(params: Optional[SmartSearchParams] = None, db: Session = Depends(get_db)):
    """Compatibilidade com o botão da interface antiga."""
    prompt = params.prompt if params else None
    run_params = JobRunSearchParams(
        primary_term=prompt or "Analista de Suporte",
        location=params.location if params else "Brasil",
        work_mode=params.work_mode if params else None,
        jobage=params.jobage if params else None,
        auto_save=True
    )
    return await run_job_search(run_params, db=db)



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
    jobs_unviewed_count = db.query(models.JobOpportunity).filter(models.JobOpportunity.is_viewed == False).count()
    jobs_interest_count = db.query(models.JobOpportunity).filter(models.JobOpportunity.user_interest == "Interesse").count()
    jobs_pcd_count = db.query(models.JobOpportunity).filter(models.JobOpportunity.pcd_type.in_(["Afirmativa PCD", "Exclusiva PCD"])).count()
    jobs_open_count = db.query(models.JobOpportunity).filter(models.JobOpportunity.is_open == True).count()

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
        "jobs_unviewed_count": jobs_unviewed_count,
        "jobs_interest_count": jobs_interest_count,
        "jobs_pcd_count": jobs_pcd_count,
        "jobs_open_count": jobs_open_count,
        "finances_count": finances_count,
        "finances_total_spent": round(finances_total_spent, 2)
    }


# --- ROTAS DA API: ANÁLISE FINANCEIRA (NUBANK & GASTOS) ---

@app.get("/api/finances/summary")
def get_finance_summary(month: Optional[str] = None, db: Session = Depends(get_db)):
    """Retorna métricas consolidadas de Entradas, Saídas, Saldo Líquido e dados para gráficos."""
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
            "total_income": month_summary["total_income"],
            "net_balance": month_summary["net_balance"],
            "total_transactions": month_summary["total_transactions"],
            "avg_monthly": global_summary["avg_monthly"],
            "avg_monthly_income": global_summary["avg_monthly_income"],
            "top_category": month_summary["top_category"],
            "top_category_amount": month_summary["top_category_amount"],
            "top_category_percent": month_summary["top_category_percent"],
            "available_months": global_summary["available_months"],
            "categories_breakdown": month_summary["categories_breakdown"],
            "monthly_breakdown": global_summary["monthly_breakdown"],
        }
    
    return {
        "selected_month": "Todos",
        "total_spent": global_summary["total_spent"],
        "total_income": global_summary["total_income"],
        "net_balance": global_summary["net_balance"],
        "total_transactions": global_summary["total_transactions"],
        "avg_monthly": global_summary["avg_monthly"],
        "avg_monthly_income": global_summary["avg_monthly_income"],
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
    tx_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lista as transações financeiras com suporte a filtros por mês, categoria, tipo (entrada/saída) e busca textual."""
    query = db.query(models.FinanceTransaction)
    
    if month and month != "Todos":
        query = query.filter(models.FinanceTransaction.month_year == month)
    if category and category != "Todas":
        query = query.filter(models.FinanceTransaction.category == category)
    if tx_type and tx_type in ["income", "expense"]:
        query = query.filter(models.FinanceTransaction.transaction_type == tx_type)
    if search:
        search_clean = search.strip()
        query = query.filter(models.FinanceTransaction.title.ilike(f"%{search_clean}%"))

    return query.order_by(models.FinanceTransaction.date.desc(), models.FinanceTransaction.id.desc()).all()

@app.post("/api/finances/transactions")
def create_finance_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    """Adiciona manualmente um gasto ou entrada."""
    clean_title = data.title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Título do lançamento é obrigatório")

    dt_obj, month_year = finance.parse_date_str(data.date)
    tx_type = data.transaction_type or "expense"
    
    category = data.category.strip() if data.category else ("Entradas" if tx_type == "income" else "Outros")
    if category in ["Outros", ""]:
        rules = db.query(models.FinanceCategoryRule).all()
        rule_dicts = [{"keyword": r.keyword, "category_name": r.category_name} for r in rules]
        category = finance.categorize_transaction(clean_title, None, rule_dicts, tx_type=tx_type)

    new_tx = models.FinanceTransaction(
        date=dt_obj,
        month_year=month_year,
        title=clean_title,
        amount=finance.parse_amount(data.amount),
        transaction_type=tx_type,
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
    """Atualiza dados de uma transação (como tipo, categoria, valor ou notas)."""
    tx = db.query(models.FinanceTransaction).filter(models.FinanceTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    if data.title is not None:
        tx.title = data.title.strip()
    if data.amount is not None:
        tx.amount = finance.parse_amount(data.amount)
    if data.transaction_type is not None:
        tx.transaction_type = data.transaction_type.strip()
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
    try:
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
                transaction_type=item.get("transaction_type", "expense"),
                category=item["category"],
                original_category=item.get("original_category"),
                payment_method=item.get("payment_method", "Extrato / Cartão Nubank")
            )
            db.add(new_tx)
            db_items.append(new_tx)

        db.commit()

        total_amt = round(sum([i["amount"] for i in parsed_items]), 2)
        incomes_count = sum(1 for i in parsed_items if i.get("transaction_type") == "income")
        expenses_count = len(parsed_items) - incomes_count
        return {
            "status": "success",
            "imported_count": len(parsed_items),
            "incomes_count": incomes_count,
            "expenses_count": expenses_count,
            "total_amount": total_amt,
            "message": f"{len(parsed_items)} lançamentos importados ({incomes_count} entradas e {expenses_count} saídas)!"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao processar upload de fatura: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar o arquivo: {str(e)}"
        )

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
            transaction_type=item.get("transaction_type", "expense"),
            category=item["category"],
            original_category=item.get("original_category"),
            payment_method=data.default_payment_method or "Fatura / Extrato Nubank"
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


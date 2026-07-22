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

# --- ROTAS PRINCIPAIS DE TEMPLATES ---

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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

    return {
        "cities_count": cities_count,
        "concursos_count": concursos_count,
        "total_topics": total_topics,
        "avg_theory": avg_theory,
        "total_questions": total_q_done,
        "avg_accuracy": avg_accuracy
    }

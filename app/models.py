from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class TargetCity(Base):
    __tablename__ = "target_cities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    uf = Column(String(2), nullable=True, default="SP")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Concurso(Base):
    __tablename__ = "concursos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    link = Column(String(500), unique=True, nullable=False)
    city = Column(String(100), index=True, nullable=False)
    state = Column(String(10), default="SP")
    status = Column(String(100), default="Em andamento")
    vacancies = Column(String(100), nullable=True)
    salary = Column(String(100), nullable=True)
    source = Column(String(50), default="PCI Concursos")
    detected_at = Column(DateTime, default=datetime.utcnow)
    notified = Column(Boolean, default=False)

class TelegramSettings(Base):
    __tablename__ = "telegram_settings"

    id = Column(Integer, primary_key=True, index=True)
    bot_token = Column(String(255), nullable=True)
    chat_id = Column(String(100), nullable=True)
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class JobPosition(Base):
    __tablename__ = "job_positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    target_exam = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    subjects = relationship("Subject", back_populates="job_position", cascade="all, delete-orphan")

class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, ForeignKey("job_positions.id"), nullable=False)
    name = Column(String(150), nullable=False)
    weight = Column(Float, default=1.0)

    job_position = relationship("JobPosition", back_populates="subjects")
    topics = relationship("Topic", back_populates="subject", cascade="all, delete-orphan")

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    title = Column(String(255), nullable=False)
    theory_percent = Column(Integer, default=0) # 0 a 100%
    reviews_count = Column(Integer, default=0)  # Qtd de revisões realizadas
    questions_done = Column(Integer, default=0)
    questions_correct = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    subject = relationship("Subject", back_populates="topics")

    @property
    def accuracy_percent(self) -> float:
        if self.questions_done and self.questions_done > 0:
            return round((self.questions_correct / self.questions_done) * 100, 1)
        return 0.0

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=True)
    headline = Column(String(255), nullable=True)
    location = Column(String(150), nullable=True)
    primary_skills = Column(Text, nullable=True)      # Separadas por vírgula (ex: Python, FastAPI, Docker, SQL)
    secondary_skills = Column(Text, nullable=True)    # Separadas por vírgula (ex: Git, Linux, Tailwind)
    experience_summary = Column(Text, nullable=True)  # Breve resumo profissional
    target_roles = Column(Text, nullable=True)        # Cargos desejados
    dealbreakers = Column(Text, nullable=True)        # Restrições (ex: apenas remoto/híbrido)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class JobSearchQuery(Base):
    __tablename__ = "job_search_queries"

    id = Column(Integer, primary_key=True, index=True)
    role_title = Column(String(150), nullable=False)
    location = Column(String(100), default="Remoto")
    work_model = Column(String(50), default="Remoto") # Remoto, Híbrido, Presencial
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class JobOpportunity(Base):
    __tablename__ = "job_opportunities"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    company = Column(String(150), nullable=False)
    location = Column(String(150), default="Remoto")
    work_model = Column(String(50), default="Remoto") # Remoto, Híbrido, Presencial
    salary = Column(String(100), nullable=True)
    link = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    skills_required = Column(Text, nullable=True)     # Requisitos identificados
    fit_score = Column(Float, default=0.0)             # Match % calculado
    status = Column(String(50), default="Nova")        # Nova, CV Gerado, Aplicado, Entrevista, Aprovado, Descartado
    
    # Novos campos para controle pessoal, PCD, status de abertura e deduplicação
    is_viewed = Column(Boolean, default=False, index=True) # Controle pessoal: Já vi ou Não
    viewed_at = Column(DateTime, nullable=True)
    user_interest = Column(String(50), default="Pendente", index=True) # Pendente, Interesse, Sem Interesse, Aplicado
    is_open = Column(Boolean, default=True, index=True) # Inscrição em aberto ou encerrada
    application_deadline = Column(String(100), nullable=True) # Prazo final informado
    pcd_type = Column(String(30), default="Ampla", index=True) # Ampla, Afirmativa PCD, Exclusiva PCD
    primary_source = Column(String(50), default="Gupy") # Plataforma principal onde foi encontrada
    other_sources = Column(Text, nullable=True) # JSON: [{"source": "LinkedIn", "link": "..."}, ...]
    dedup_hash = Column(String(64), index=True, nullable=True) # Chave para deduplicação entre plataformas
    last_checked_at = Column(DateTime, default=datetime.utcnow) # Data da última checagem de status
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



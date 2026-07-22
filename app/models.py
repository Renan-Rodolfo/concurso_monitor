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

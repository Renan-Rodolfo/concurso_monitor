import os
import logging
import httpx
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models import TelegramSettings, Concurso

logger = logging.getLogger("telegram_notifier")

def get_telegram_config(db: Optional[Session] = None):
    token = None
    chat_id = None
    enabled = True

    if db:
        config = db.query(TelegramSettings).first()
        if config and config.bot_token and config.chat_id:
            token = config.bot_token
            chat_id = config.chat_id
            enabled = config.enabled

    if not token or not chat_id:
        token = os.getenv("TELEGRAM_BOT_TOKEN", token)
        chat_id = os.getenv("TELEGRAM_CHAT_ID", chat_id)
        enabled_str = os.getenv("TELEGRAM_ENABLED", "true").lower()
        enabled = enabled_str in ("true", "1", "yes")

    return token, chat_id, enabled

async def send_telegram_message(message: str, db: Optional[Session] = None, token_override: Optional[str] = None, chat_id_override: Optional[str] = None) -> bool:
    token = token_override
    chat_id = chat_id_override
    enabled = True

    if not token or not chat_id:
        token, chat_id, enabled = get_telegram_config(db)

    if not enabled or not token or not chat_id:
        logger.info("Notificação do Telegram desativada ou credenciais não configuradas.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Notificação enviada com sucesso no Telegram.")
                return True
            else:
                logger.error(f"Erro ao enviar mensagem no Telegram ({resp.status_code}): {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Exceção ao conectar à Telegram Bot API: {e}")
        return False

async def notify_new_concursos(concursos: List[Concurso], db: Session) -> int:
    if not concursos:
        return 0

    sent_count = 0
    for item in concursos:
        msg = (
            f"🚨 <b>Novo Concurso Detectado!</b> 🚨\n\n"
            f"🏛️ <b>Título:</b> {item.title}\n"
            f"📍 <b>Cidade/UF:</b> {item.city} / {item.state}\n"
            f"💼 <b>Vagas:</b> {item.vacancies or 'Não informado'}\n"
            f"💰 <b>Salário:</b> {item.salary or 'Não informado'}\n"
            f"📌 <b>Status:</b> {item.status}\n"
            f"🌐 <b>Fonte:</b> {item.source}\n\n"
            f"🔗 <a href='{item.link}'>Acessar Edital / Detalhes</a>"
        )

        success = await send_telegram_message(msg, db=db)
        if success:
            item.notified = True
            sent_count += 1

    if sent_count > 0:
        db.commit()

    return sent_count

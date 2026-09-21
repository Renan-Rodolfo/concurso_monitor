import os
import logging
import httpx
from typing import Optional, List, Any
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


async def notify_new_jobs(jobs: List[Any], db: Session) -> int:
    """
    Envia alertas no Telegram para novas vagas detectadas.
    Formata com cargo, empresa, localização, modalidade, status de abertura, política PCD e fontes com links.
    """
    if not jobs:
        return 0

    sent_count = 0
    for job in jobs:
        pcd_label = (
            "♿ <b>Vaga Exclusiva PCD</b>" if job.pcd_type == "Exclusiva PCD"
            else "🤝 <b>Vaga Afirmativa PCD</b>" if job.pcd_type == "Afirmativa PCD"
            else "👥 <b>Ampla Concorrência</b>"
        )
        
        status_label = "🟢 <b>Inscrição Em Aberto</b>"
        if job.application_deadline:
            status_label += f" (Até {job.application_deadline})"
            
        # Montar links das fontes encontradas
        sources_links = []
        if job.other_sources:
            try:
                import json
                s_list = json.loads(job.other_sources)
                for s in s_list:
                    src_name = s.get("source", "Link")
                    src_url = s.get("link", "")
                    if src_url:
                        sources_links.append(f"<a href='{src_url}'>{src_name}</a>")
            except Exception:
                pass

        if not sources_links and job.link:
            sources_links.append(f"<a href='{job.link}'>{job.primary_source or 'Candidatar-se'}</a>")

        sources_html = " | ".join(sources_links) if sources_links else "Link direto não informado"

        msg = (
            f"💼 <b>Nova Vaga Detectada!</b> 💼\n\n"
            f"📋 <b>Cargo:</b> {job.title}\n"
            f"🏢 <b>Empresa:</b> {job.company}\n"
            f"📍 <b>Local:</b> {job.location} ({job.work_model})\n"
            f"{pcd_label}\n"
            f"{status_label}\n"
            f"🌐 <b>Onde se candidatar:</b> {sources_html}\n"
        )

        success = await send_telegram_message(msg, db=db)
        if success:
            sent_count += 1

    return sent_count


import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("english_daily")
scheduler = BackgroundScheduler()

# Quiet APScheduler's own logger
logging.getLogger("apscheduler").setLevel(logging.WARNING)


def generate_daily_article(app):
    """Generate article if none exists for today."""
    from db import get_connection, _db_fetch_one

    today = datetime.now().strftime("%Y-%m-%d")
    db = get_connection()
    existing = _db_fetch_one(db, "SELECT id FROM articles WHERE DATE(created_at) = %s", (today,))
    db.close()

    if existing:
        return

    from generator import generate_article
    try:
        article_id = generate_article()
        logger.info(f"Daily article generated: id={article_id}")
    except Exception as e:
        logger.error(f"Daily article generation failed: {e}")


def start_scheduler(app):
    scheduler.add_job(
        func=lambda: generate_daily_article(app),
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_article",
        name="Generate daily English article",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: daily article at 08:00")

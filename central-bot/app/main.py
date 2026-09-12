import logging
import asyncio
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.database import init_db
from app.discord_bot import bot
from app.config import settings

# config logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gmail Discord Bot API",
    description="Email Notifications Bot",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    init_db()
    logger.info("Database initialized")

@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "healthy",
        "service": "Gmail Discord Bot",
        "version": "2.0.0",
    }

def run_fastapi():
    """Run FastAPI server"""
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
        log_level="info",
    )

def run_mailbot():
    """Run Discord bot"""
    bot.run(settings.DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    logger.info("Starting mailbot")

    #initialize database
    init_db()

    # Run FastAPI in background thread
    api_thread = threading.Thread(target=run_fastapi, daemon=True)
    api_thread.start()

    run_mailbot()

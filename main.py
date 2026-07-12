#!/usr/bin/env python3
import os
import threading
from dotenv import load_dotenv

# Must run BEFORE any src.* imports — modules like src.city_scene read env vars
# at import time via os.getenv() with hardcoded defaults. Loading .env after
# those imports silently fell back to the defaults, ignoring .env values.
load_dotenv()

from src.bot import run_discord_bot
from src.log import logger

def _start_dashboard():
    try:
        from Webpage.app import app
        port = int(os.getenv("DASHBOARD_PORT", 5000))
        # threaded=True: image-heavy dashboard pages request dozens of PNGs in
        # parallel; the single-threaded default serialized every request.
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.warning(f"Dashboard failed to start: {e}")

def validate_environment():
    """Validate required environment variables"""
    required_vars = ["DISCORD_BOT_TOKEN"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file")
        return False
    
    providers = []
    if os.getenv("OPENAI_KEY"):
        providers.append("OpenAI")
    if os.getenv("CLAUDE_KEY"):
        providers.append("Claude")
    if os.getenv("GEMINI_KEY"):
        providers.append("Gemini")
    if os.getenv("GROK_KEY"):
        providers.append("Grok")
    
    providers.append("Free (always available)")
    
    logger.info(f"Available providers: {', '.join(providers)}")
    
    return True

def main():
    """Main entry point"""
    logger.info("Starting Discord AI Bot...")

    if not validate_environment():
        return

    dashboard_thread = threading.Thread(target=_start_dashboard, daemon=True, name="dashboard")
    dashboard_thread.start()
    logger.info(f"Dashboard thread started on port {os.getenv('DASHBOARD_PORT', 5000)}")

    logger.info("Free provider configured - no authentication required")

    try:
        run_discord_bot()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise

if __name__ == "__main__":
    main()

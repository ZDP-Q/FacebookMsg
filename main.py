import uvicorn

import logging
from pathlib import Path
from app.application import create_app

# 确保日志目录存在
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("uvicorn.error")

app = create_app()

if __name__ == "__main__":
    try:
        # reload=False is safer for signal handling in some Windows environments
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
    except (KeyboardInterrupt, SystemExit):
        # Graceful exit without printing Traceback noise
        pass

        pass

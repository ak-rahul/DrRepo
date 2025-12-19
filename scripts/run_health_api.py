"""Run the health check API server."""

import uvicorn
from src.utils.logger import logger

if __name__ == "__main__":
    logger.info("Starting DrRepo Health Check API...")
    
    uvicorn.run(
        "src.api.health:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

import logging
import os

import uvicorn

from .main import creer_application

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
uvicorn.run(
    creer_application(),
    host=os.environ.get("AC_HOTE", "127.0.0.1"),
    port=int(os.environ.get("AC_PORT", "8000")),
)

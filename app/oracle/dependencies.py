from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.oracle.clinician_chat import ClinicianChatOracle
from app.oracle.contract import Oracle
from app.oracle.fake import FakeOracle


def get_oracle() -> Oracle:
    """FastAPI dependency (the worker calls it too). `settings.oracle_backend` picks the fake or
    the clinician streaming chat API (app/oracle/clinician_chat.py)."""
    if settings.environment == "production":
        raise RuntimeError(
            "No Oracle service is configured for production: the safety check (story 3.2) is "
            "still the fake, with either ORACLE_BACKEND."
        )
    if settings.oracle_backend in ("clinician", "senior"):
        return ClinicianChatOracle()
    return FakeOracle()


OracleService = Annotated[Oracle, Depends(get_oracle)]

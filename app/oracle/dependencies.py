from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.oracle.contract import Oracle
from app.oracle.fake import FakeOracle


def get_oracle() -> Oracle:
    """FastAPI dependency. Return the real Oracle client here once the AI team's service is
    ready."""
    if settings.environment == "production":
        # The fake would answer real clients with canned replies and no safety check.
        raise RuntimeError("No Oracle service is configured for production.")
    return FakeOracle()


OracleService = Annotated[Oracle, Depends(get_oracle)]

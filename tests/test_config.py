import pytest
from pydantic import ValidationError

from app.config import Settings


def test_dev_secret_is_rejected_outside_dev():
    with pytest.raises(ValidationError):
        Settings(
            app_env="prod",
            jwt_secret="dev-only-insecure-secret-change-me-0123456789",
        )

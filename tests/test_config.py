import pytest
from pydantic import ValidationError

from app.config import Settings


def test_dev_secret_is_rejected_outside_dev():
    with pytest.raises(ValidationError):
        Settings(
            app_env="prod",
            jwt_secret="dev-only-insecure-secret-change-me-0123456789",
        )


def test_webhook_secret_is_required_outside_dev():
    with pytest.raises(ValidationError):
        Settings(
            app_env="prod",
            jwt_secret="production-secret-0123456789",
            webhook_secret_key="",
        )

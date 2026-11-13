"""Общие фикстуры для тестов EduSlot."""

import os
import tempfile
from pathlib import Path

# Отдельная тестовая БД — задаём до импорта приложения.
TEST_DB = Path(tempfile.gettempdir()) / "college_test.db"
os.environ["EDUSLOT_DB"] = str(TEST_DB)
os.environ["EDUSLOT_SEED"] = "1"
if TEST_DB.exists():
    TEST_DB.unlink()

import pytest
from fastapi.testclient import TestClient

from app.database import engine
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"username": username, "password": password, "next": "/schedule"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


@pytest.fixture()
def teacher_client(client):
    login(client, "teacher", "teacher123")
    return client


@pytest.fixture()
def admin_client(client):
    login(client, "admin", "admin123")
    return client


@pytest.fixture()
def student_client(client):
    login(client, "student", "student123")
    return client

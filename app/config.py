"""Настройки приложения EduSlot."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

APP_NAME = "EduSlot"
APP_SUBTITLE = "Информационная система управления аудиториями"

# --- База данных -----------------------------------------------------------
# На Vercel файловая система доступна только для записи в /tmp,
# поэтому путь по умолчанию зависит от окружения.
if os.getenv("VERCEL"):
    DEFAULT_DB_PATH = "/tmp/college.db"
else:
    DEFAULT_DB_PATH = str(BASE_DIR / "data" / "college.db")

DB_PATH = os.getenv("EDUSLOT_DB", DEFAULT_DB_PATH)
DATABASE_URL = f"sqlite:///{DB_PATH}"

# --- Безопасность ----------------------------------------------------------
SECRET_KEY = os.getenv("EDUSLOT_SECRET", "eduslot-dev-secret-change-me")
SESSION_COOKIE = "eduslot_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 часов

# --- Демо-данные -----------------------------------------------------------
SEED_ON_START = os.getenv("EDUSLOT_SEED", "1") == "1"

# --- Учебные пары ----------------------------------------------------------
TIME_SLOTS = [
    {"number": 1, "start": "08:30", "end": "10:00"},
    {"number": 2, "start": "10:10", "end": "11:40"},
    {"number": 3, "start": "12:10", "end": "13:40"},
    {"number": 4, "start": "14:00", "end": "15:30"},
    {"number": 5, "start": "15:40", "end": "17:10"},
    {"number": 6, "start": "17:20", "end": "18:50"},
    {"number": 7, "start": "19:00", "end": "20:30"},
]

SLOT_BY_NUMBER = {slot["number"]: slot for slot in TIME_SLOTS}
SLOTS_PER_DAY = len(TIME_SLOTS)

EQUIPMENT_OPTIONS = [
    "Проектор",
    "Компьютеры",
    "Интерактивная доска",
    "Маркерная доска",
    "Кондиционер",
]

BUILDINGS = ["Корпус A", "Корпус B", "Корпус C"]

ROLE_LABELS = {
    "admin": "Администратор",
    "teacher": "Преподаватель",
    "student": "Студент",
}

ROOM_STATUS_LABELS = {
    "available": "Доступна",
    "maintenance": "На ремонте",
}

BOOKING_STATUS_LABELS = {
    "active": "Активна",
    "cancelled": "Отменена",
}

"""Слой доступа к данным: DatabaseManager (движок, сессии, инициализация)."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL, DB_PATH


class DatabaseManager:
    """Управляет подключением к БД и выдаёт сессии (UML: DatabaseManager)."""

    def __init__(self, db_url: str = DATABASE_URL):
        self.db_url = db_url
        # Каталог data/ создаётся автоматически при первом запуске.
        if db_url.startswith("sqlite:///"):
            Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False — чтобы SQLite работал с несколькими потоками FastAPI.
        self.engine = create_engine(
            self.db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def init_db(self) -> None:
        """Создать таблицы, если их ещё нет."""
        SQLModel.metadata.create_all(self.engine)

    def get_session(self) -> Iterator[Session]:
        """FastAPI-зависимость: сессия БД на один запрос."""
        with self.session_factory() as session:
            yield session


db_manager = DatabaseManager()
engine = db_manager.engine
get_session = db_manager.get_session
init_db = db_manager.init_db

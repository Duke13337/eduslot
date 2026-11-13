"""Модели предметной области (SQLModel / SQLite)."""

from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Session, SQLModel, select


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo — единый формат для SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class College(SQLModel, table=True):
    """Учебное заведение — верхний уровень «Хаба колледжей»."""

    __tablename__ = "colleges"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=150)
    short_name: str = Field(default="", max_length=30)
    city: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=200)


class User(SQLModel, table=True):
    """Пользователь системы: администратор, преподаватель или студент."""

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    full_name: str = Field(default="", max_length=120)
    password_hash: str = Field(default="")
    role: str = Field(default="teacher", max_length=20)
    college_id: Optional[int] = Field(default=None, foreign_key="colleges.id")
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_book(self) -> bool:
        return self.role in ("admin", "teacher")

    def login(self, password: str) -> bool:
        """Проверить пароль пользователя (UML: +login())."""
        from .security import verify_password

        return verify_password(password, self.password_hash)

    def get_profile(self) -> dict:
        """Профиль пользователя для интерфейса (UML: +get_profile())."""
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "role": self.role,
        }


class Auditorium(SQLModel, table=True):
    """Учебное помещение (аудитория, кабинет, лаборатория)."""

    __tablename__ = "auditoriums"

    id: Optional[int] = Field(default=None, primary_key=True)
    college_id: Optional[int] = Field(default=None, foreign_key="colleges.id", index=True)
    number: str = Field(index=True, max_length=20)
    building: str = Field(default="Корпус A", max_length=50)
    floor: int = Field(default=1, ge=1, le=10)
    capacity: int = Field(default=20, ge=1, le=500)
    equipment: str = Field(default="", max_length=255)
    status: str = Field(default="available", max_length=20)
    description: str = Field(default="", max_length=500)
    map_x: int = Field(default=1, ge=1, le=6)
    map_y: int = Field(default=1, ge=1, le=6)

    @property
    def equipment_list(self) -> list[str]:
        return [item.strip() for item in self.equipment.split(",") if item.strip()]

    @property
    def is_available(self) -> bool:
        return self.status == "available"

    @property
    def title(self) -> str:
        return f"Ауд. {self.number}"

    def check_availability(
        self,
        session: Session,
        on_date: date_type,
        time_slot: int,
    ) -> bool:
        """Свободна ли аудитория в указанный слот (UML: +check_availability())."""
        if not self.is_available:
            return False
        statement = select(Booking).where(
            Booking.room_id == self.id,
            Booking.date == on_date,
            Booking.time_slot == time_slot,
            Booking.status == "active",
        )
        return session.exec(statement).first() is None


class Booking(SQLModel, table=True):
    """Заявка на бронирование аудитории."""

    __tablename__ = "bookings"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    room_id: int = Field(foreign_key="auditoriums.id", index=True)
    date: date_type = Field(index=True)
    time_slot: int = Field(ge=1, le=7)
    purpose: str = Field(default="", max_length=255)
    status: str = Field(default="active", max_length=20, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    cancelled_at: Optional[datetime] = Field(default=None)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def validate(self, session: Session) -> list[str]:
        """Проверить заявку на коллизии и ограничения (UML: +validate())."""
        from .services import validate_booking

        user = session.get(User, self.user_id)
        room = session.get(Auditorium, self.room_id)
        if user is None or room is None:
            return ["Пользователь или аудитория не найдены."]
        return validate_booking(
            session,
            user,
            room,
            self.date,
            self.time_slot,
            exclude_id=self.id,
        )

    def create(self, session: Session) -> "Booking":
        """Сохранить заявку после проверки (UML: +create())."""
        errors = self.validate(session)
        if errors:
            raise ValueError("; ".join(errors))
        session.add(self)
        session.commit()
        session.refresh(self)
        return self

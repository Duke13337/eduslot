"""Демонстрационные данные: колледжи, пользователи, аудитории и брони."""

from datetime import date as date_type
from datetime import timedelta

from sqlmodel import Session, select

from .database import engine
from .models import Auditorium, Booking, College, User
from .security import hash_password


DEMO_COLLEGES = [
    {
        "name": "Колледж информационных технологий",
        "short_name": "КИТ",
        "city": "Москва",
        "address": "ул. Пушкина, 10",
    },
    {
        "name": "Политехнический колледж",
        "short_name": "ПК",
        "city": "Москва",
        "address": "пр-т Мира, 25",
    },
    {
        "name": "Колледж дизайна и сервиса",
        "short_name": "КДС",
        "city": "Москва",
        "address": "ул. Тверская, 7",
    },
]

DEMO_USERS = [
    ("admin", "admin123", "Администратор системы", "admin", None),
    ("teacher", "teacher123", "Иванов Иван Иванович", "teacher", 0),
    ("student", "student123", "Петров Пётр Петрович", "student", 0),
]

DEMO_ROOMS = [
    {
        "college": 0,
        "number": "101",
        "building": "Корпус A",
        "floor": 1,
        "capacity": 30,
        "equipment": "Проектор, Маркерная доска",
        "description": "Лекционная аудитория",
        "map_x": 1,
        "map_y": 1,
    },
    {
        "college": 0,
        "number": "102",
        "building": "Корпус A",
        "floor": 1,
        "capacity": 25,
        "equipment": "Проектор, Компьютеры",
        "description": "Компьютерный класс",
        "map_x": 3,
        "map_y": 1,
    },
    {
        "college": 0,
        "number": "203",
        "building": "Корпус A",
        "floor": 2,
        "capacity": 20,
        "equipment": "Компьютеры, Интерактивная доска",
        "description": "Лаборатория программирования",
        "map_x": 1,
        "map_y": 1,
    },
    {
        "college": 0,
        "number": "204",
        "building": "Корпус A",
        "floor": 2,
        "capacity": 15,
        "equipment": "Маркерная доска",
        "description": "Аудитория для семинаров",
        "map_x": 3,
        "map_y": 1,
    },
    {
        "college": 1,
        "number": "305",
        "building": "Корпус B",
        "floor": 3,
        "capacity": 40,
        "equipment": "Проектор, Кондиционер",
        "description": "Актовый зал малой формы",
        "map_x": 1,
        "map_y": 2,
    },
    {
        "college": 1,
        "number": "306",
        "building": "Корпус B",
        "floor": 3,
        "capacity": 24,
        "equipment": "Компьютеры, Проектор, Кондиционер",
        "description": "Мультимедийный кабинет",
        "map_x": 3,
        "map_y": 2,
    },
    {
        "college": 2,
        "number": "410",
        "building": "Корпус C",
        "floor": 4,
        "capacity": 18,
        "equipment": "Интерактивная доска",
        "description": "Аудитория для иностранных языков",
        "map_x": 2,
        "map_y": 1,
    },
    {
        "college": 2,
        "number": "411",
        "building": "Корпус C",
        "floor": 4,
        "capacity": 12,
        "equipment": "Маркерная доска",
        "status": "maintenance",
        "description": "Закрыта на ремонт",
        "map_x": 4,
        "map_y": 1,
    },
]

DEMO_BOOKINGS = [
    ("teacher", "101", 0, 1, "Лекция по информатике"),
    ("teacher", "101", 0, 2, "Лекция по информатике"),
    ("teacher", "203", 1, 3, "Практика по Python"),
    ("admin", "306", 1, 4, "Совещание отделения"),
]


def seed_demo_data() -> None:
    """Заполнить базу демо-данными, если она пустая."""
    with Session(engine) as session:
        if session.exec(select(User)).first():
            return

        colleges: list[College] = []
        for payload in DEMO_COLLEGES:
            college = College(**payload)
            session.add(college)
            colleges.append(college)
        session.commit()

        users: dict[str, User] = {}
        for username, password, full_name, role, college_index in DEMO_USERS:
            user = User(
                username=username,
                full_name=full_name,
                password_hash=hash_password(password),
                role=role,
                college_id=colleges[college_index].id if college_index is not None else None,
            )
            session.add(user)
            users[username] = user
        session.commit()

        rooms: dict[str, Auditorium] = {}
        for payload in DEMO_ROOMS:
            data = dict(payload)
            college_index = data.pop("college")
            room = Auditorium(college_id=colleges[college_index].id, **data)
            session.add(room)
            rooms[room.number] = room
        session.commit()

        today = date_type.today()
        for username, room_number, day_offset, slot, purpose in DEMO_BOOKINGS:
            user = users[username]
            room = rooms[room_number]
            session.add(
                Booking(
                    user_id=user.id,
                    room_id=room.id,
                    date=today + timedelta(days=day_offset),
                    time_slot=slot,
                    purpose=purpose,
                )
            )
        session.commit()

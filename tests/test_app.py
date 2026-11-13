"""Тесты основных сценариев системы EduSlot."""

from datetime import date, timedelta

from sqlmodel import Session, select

from app.database import engine
from app.models import Auditorium, Booking, College, User
from tests.conftest import login


def room_by_number(number: str) -> Auditorium:
    with Session(engine) as session:
        return session.exec(select(Auditorium).where(Auditorium.number == number)).first()


def college_by_short(short_name: str) -> College:
    with Session(engine) as session:
        return session.exec(select(College).where(College.short_name == short_name)).first()


def user_by_username(username: str) -> User:
    with Session(engine) as session:
        return session.exec(select(User).where(User.username == username)).first()


def test_schedule_requires_login(client):
    response = client.get("/schedule", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_success(teacher_client):
    response = teacher_client.get("/schedule")
    assert response.status_code == 200
    assert "Расписание аудиторий" in response.text


def test_login_wrong_password(client):
    response = client.post(
        "/login",
        data={"username": "teacher", "password": "wrong", "next": "/schedule"},
    )
    assert response.status_code == 401
    assert "Неверный логин или пароль" in response.text


def test_teacher_can_book_free_slot(teacher_client):
    room = room_by_number("204")
    response = teacher_client.post(
        "/book",
        data={
            "room_id": room.id,
            "date": (date.today() + timedelta(days=3)).isoformat(),
            "time_slot": 2,
            "purpose": "Семинар",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        booking = session.exec(
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.time_slot == 2,
                Booking.status == "active",
            )
        ).first()
        assert booking is not None
        assert booking.purpose == "Семинар"


def test_conflict_is_blocked(teacher_client):
    room = room_by_number("101")
    response = teacher_client.post(
        "/book",
        data={
            "room_id": room.id,
            "date": date.today().isoformat(),
            "time_slot": 1,
            "purpose": "Повторная заявка",
        },
    )
    assert response.status_code == 400
    assert "Слот уже занят" in response.text


def test_book_page_redirects_for_occupied_slot(teacher_client):
    room = room_by_number("101")
    response = teacher_client.get(
        f"/book?room_id={room.id}&date={date.today().isoformat()}&slot=1",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/schedule")


def test_student_cannot_book(student_client):
    room = room_by_number("203")
    response = student_client.post(
        "/book",
        data={
            "room_id": room.id,
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "time_slot": 5,
            "purpose": "Хочу занятие",
        },
    )
    assert response.status_code == 400
    assert "Студенты могут только просматривать" in response.text


def test_past_date_is_rejected(teacher_client):
    room = room_by_number("203")
    response = teacher_client.post(
        "/book",
        data={
            "room_id": room.id,
            "date": (date.today() - timedelta(days=1)).isoformat(),
            "time_slot": 4,
            "purpose": "Вчера",
        },
    )
    assert response.status_code == 400
    assert "прошедшую дату" in response.text


def test_cancel_frees_slot(teacher_client):
    room = room_by_number("306")
    on_date = (date.today() + timedelta(days=4)).isoformat()

    first = teacher_client.post(
        "/book",
        data={"room_id": room.id, "date": on_date, "time_slot": 3, "purpose": "Практика"},
        follow_redirects=False,
    )
    assert first.status_code == 303

    with Session(engine) as session:
        booking = session.exec(
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.time_slot == 3,
                Booking.status == "active",
            )
        ).first()
        booking_id = booking.id

    cancel = teacher_client.post(
        f"/bookings/{booking_id}/cancel",
        headers={"referer": "/my"},
        follow_redirects=False,
    )
    assert cancel.status_code == 303

    second = teacher_client.post(
        "/book",
        data={"room_id": room.id, "date": on_date, "time_slot": 3, "purpose": "Снова практика"},
        follow_redirects=False,
    )
    assert second.status_code == 303


def test_filter_by_capacity(teacher_client):
    response = teacher_client.get("/schedule?capacity=30")
    assert response.status_code == 200
    assert "Ауд. 101" in response.text
    assert "Ауд. 305" in response.text
    assert "Ауд. 204" not in response.text


def test_filter_by_equipment(teacher_client):
    response = teacher_client.get("/schedule?equipment=Компьютеры")
    assert response.status_code == 200
    assert "Ауд. 102" in response.text
    assert "Ауд. 101" not in response.text


def test_student_cannot_open_admin(student_client):
    response = student_client.get("/admin/rooms")
    assert response.status_code == 403
    assert "Доступ запрещён" in response.text


def test_admin_can_create_room(admin_client):
    college = college_by_short("КИТ")
    response = admin_client.post(
        "/admin/rooms/save",
        data={
            "college_id": college.id,
            "number": "999",
            "building": "Корпус C",
            "floor": 2,
            "capacity": 22,
            "equipment": ["Проектор", "Компьютеры"],
            "status": "available",
            "description": "Тестовая аудитория",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert room_by_number("999") is not None

    page = admin_client.get("/admin/rooms")
    assert "999" in page.text


def test_admin_room_number_must_be_unique(admin_client):
    college = college_by_short("КИТ")
    response = admin_client.post(
        "/admin/rooms/save",
        data={
            "college_id": college.id,
            "number": "101",
            "building": "Корпус A",
            "floor": 1,
            "capacity": 30,
            "status": "available",
        },
    )
    assert response.status_code == 400
    assert "уже есть в этом колледже" in response.text


def test_maintenance_room_cannot_be_booked(admin_client):
    room = room_by_number("411")
    response = admin_client.post(
        "/book",
        data={
            "room_id": room.id,
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "time_slot": 2,
            "purpose": "Занятие",
        },
    )
    assert response.status_code == 400
    assert "находится на ремонте" in response.text


def test_report_page(admin_client):
    response = admin_client.get("/admin/report")
    assert response.status_code == 200
    assert "Загруженность фонда" in response.text


def test_admin_sees_all_bookings(admin_client):
    response = admin_client.get("/admin/bookings")
    assert response.status_code == 200
    assert "Все заявки" in response.text


def test_owner_sees_own_bookings(teacher_client):
    response = teacher_client.get("/my")
    assert response.status_code == 200
    assert "Мои бронирования" in response.text
    assert "Ауд. 101" in response.text
    assert "Отменить" in response.text


def test_hub_lists_colleges(teacher_client):
    response = teacher_client.get("/hub")
    assert response.status_code == 200
    assert "Хаб колледжей" in response.text
    assert "Колледж информационных технологий" in response.text
    assert "Политехнический колледж" in response.text


def test_college_map_renders_floor_plan(teacher_client):
    college = college_by_short("КИТ")
    response = teacher_client.get(f"/college/{college.id}")
    assert response.status_code == 200
    assert "План 1 этажа" in response.text
    assert "101" in response.text
    assert "floor-plan" in response.text


def test_college_map_unknown_college_redirects(teacher_client):
    response = teacher_client.get("/college/9999", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/hub"


def test_schedule_filters_by_college(teacher_client):
    college = college_by_short("ПК")
    response = teacher_client.get(f"/schedule?college_id={college.id}")
    assert response.status_code == 200
    assert "Ауд. 305" in response.text
    assert "Ауд. 101" not in response.text


def test_schedule_accepts_empty_filter_values(teacher_client):
    response = teacher_client.get(
        "/schedule?date=2026-11-13&college_id=&building=&capacity=&equipment=&query="
    )
    assert response.status_code == 200


def test_classes_match_uml():
    from app.database import DatabaseManager
    from app.security import AuthController
    from app.services import ConflictChecker, RoomFilter

    manager = DatabaseManager()
    assert manager.db_url.startswith("sqlite:///")
    assert manager.engine is not None
    assert manager.session_factory is not None

    controller = AuthController()
    assert controller.secret_key
    assert controller.token_expire > 0
    assert controller.algorithm == "HS256"

    room = room_by_number("101")
    with Session(engine) as session:
        checker = ConflictChecker(
            session,
            {"room_id": room.id, "date": date.today(), "time_slot": 1},
        )
        assert checker.check_collision() is not None
        assert checker.has_conflict(room.id, date.today(), 1) is True

        room_filter = RoomFilter(session, {"min_capacity": 25})
        rooms = room_filter.apply_filters()
        assert all(item.capacity >= 25 for item in rooms)
        assert room_filter.filters_list


def test_booking_create_and_validate():
    room = room_by_number("204")
    on_date = date.today() + timedelta(days=6)

    with Session(engine) as session:
        booking = Booking(
            user_id=user_by_username("teacher").id,
            room_id=room.id,
            date=on_date,
            time_slot=7,
            purpose="Проверка UML-методов",
        )
        assert booking.validate(session) == []
        created = booking.create(session)
        assert created.id is not None

        duplicate = Booking(
            user_id=user_by_username("teacher").id,
            room_id=room.id,
            date=on_date,
            time_slot=7,
            purpose="Дубль",
        )
        assert duplicate.validate(session)
        try:
            duplicate.create(session)
        except ValueError as error:
            assert "Слот уже занят" in str(error)
        else:
            raise AssertionError("Ожидалась ошибка коллизии")

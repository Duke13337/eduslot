"""EduSlot — веб-приложение для бронирования аудиторий колледжа.

Точка входа FastAPI: маршруты интерфейса, авторизация, бронирование,
административная панель и отчёты.
"""

from collections import Counter
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware

from .config import (
    APP_NAME,
    APP_SUBTITLE,
    BASE_DIR,
    BOOKING_STATUS_LABELS,
    BUILDINGS,
    EQUIPMENT_OPTIONS,
    ROLE_LABELS,
    ROOM_STATUS_LABELS,
    SECRET_KEY,
    SEED_ON_START,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    SLOT_BY_NUMBER,
    TIME_SLOTS,
)
from .database import engine, get_session, init_db
from .models import Auditorium, Booking, College, User, utcnow
from .security import (
    LoginRequired,
    auth_controller,
    authenticate,
    flash,
    get_current_user,
    hash_password,
    login_url,
    pop_flash,
    require_admin,
    require_user,
)
from .seed import seed_demo_data
from .services import (
    ConflictChecker,
    RoomFilter,
    build_schedule,
    utilization_report,
    week_bounds,
    validate_booking,
)

TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if SEED_ON_START:
        seed_demo_data()
    yield


app = FastAPI(title=APP_NAME, description=APP_SUBTITLE, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    app_name=APP_NAME,
    app_subtitle=APP_SUBTITLE,
    time_slots=TIME_SLOTS,
    slot_by_number=SLOT_BY_NUMBER,
    equipment_options=EQUIPMENT_OPTIONS,
    buildings=BUILDINGS,
    role_labels=ROLE_LABELS,
    room_status_labels=ROOM_STATUS_LABELS,
    booking_status_labels=BOOKING_STATUS_LABELS,
    today=lambda: date_type.today(),
)


def render(request: Request, template: str, user: Optional[User], status_code: int = 200, **context):
    return templates.TemplateResponse(
        request,
        template,
        {"user": user, "flash_messages": pop_flash(request), **context},
        status_code=status_code,
    )


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(login_url(exc.next_url), status_code=303)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_403_FORBIDDEN and request.method == "GET":
        with Session(engine) as session:
            user = get_current_user(request, session)
        return render(request, "error.html", user, status_code=403, message=exc.detail)
    return RedirectResponse(url="/schedule", status_code=303)


def parse_date(value: Optional[str], default: Optional[date_type] = None) -> date_type:
    if value:
        try:
            return date_type.fromisoformat(value)
        except ValueError:
            pass
    return default or date_type.today()


# --------------------------------------------------------------------------
# Авторизация и регистрация
# --------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str = "/schedule",
    session: Session = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    if user:
        return RedirectResponse("/schedule", status_code=303)
    return render(request, "login.html", None, next_url=next)


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/schedule"),
    session: Session = Depends(get_session),
):
    user = authenticate(session, username, password)
    if not user:
        return render(
            request,
            "login.html",
            None,
            status_code=401,
            error="Неверный логин или пароль.",
            next_url=next,
            username=username,
        )
    auth_controller.start_session(request, user)
    flash(request, f"Добро пожаловать, {user.full_name or user.username}!")
    target = next if next.startswith("/") else "/schedule"
    return RedirectResponse(target, status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
):
    if user:
        return RedirectResponse("/schedule", status_code=303)
    return render(request, "register.html", None)


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(""),
    full_name: str = Form(""),
    password: str = Form(""),
    password_repeat: str = Form(""),
    role: str = Form("teacher"),
    session: Session = Depends(get_session),
):
    username = username.strip()
    errors: list[str] = []
    if len(username) < 3:
        errors.append("Логин должен содержать минимум 3 символа.")
    if len(password) < 6:
        errors.append("Пароль должен содержать минимум 6 символов.")
    if password != password_repeat:
        errors.append("Пароли не совпадают.")
    if role not in ("teacher", "student"):
        errors.append("Недопустимая роль.")
    if session.exec(select(User).where(User.username == username)).first():
        errors.append("Такой логин уже занят.")

    if errors:
        return render(
            request,
            "register.html",
            None,
            status_code=400,
            errors=errors,
            username=username,
            full_name=full_name,
            role=role,
        )

    user = User(
        username=username,
        full_name=full_name.strip() or username,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    auth_controller.start_session(request, user)
    flash(request, "Регистрация завершена. Аккаунт создан.")
    return RedirectResponse("/schedule", status_code=303)


@app.post("/logout")
def logout(request: Request):
    auth_controller.end_session(request)
    return RedirectResponse("/login", status_code=303)


# --------------------------------------------------------------------------
# Расписание и бронирование
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/schedule", status_code=303)


@app.get("/health")
def health():
    """Проверка доступности приложения (для мониторинга и деплоя)."""
    return {"status": "ok", "app": APP_NAME}


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    date: Optional[str] = Query(None),
    college_id: str = Query(""),
    building: str = Query(""),
    capacity: str = Query(""),
    equipment: str = Query(""),
    query: str = Query(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    on_date = parse_date(date)
    college_value = int(college_id) if college_id.isdigit() else 0
    capacity_value = int(capacity) if capacity.isdigit() else 0
    room_filter = RoomFilter(
        session,
        {
            "college_id": college_value or None,
            "building": building,
            "min_capacity": capacity_value or None,
            "equipment": equipment,
            "query": query,
        },
    )
    rooms = room_filter.apply_filters()
    rows = build_schedule(session, rooms, on_date, user)
    colleges = list(session.exec(select(College).order_by(College.name)).all())
    selected_college = session.get(College, college_value) if college_value else None

    return render(
        request,
        "schedule.html",
        user,
        rows=rows,
        on_date=on_date,
        prev_date=on_date - timedelta(days=1),
        next_date=on_date + timedelta(days=1),
        filters={
            "college_id": college_value or "",
            "building": building,
            "capacity": capacity_value or "",
            "equipment": equipment,
            "query": query,
        },
        colleges=colleges,
        selected_college=selected_college,
        total_rooms=len(rooms),
        free_cells=sum(1 for row in rows for cell in row["cells"] if cell["state"] == "free"),
    )


@app.get("/hub", response_class=HTMLResponse)
def hub_page(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    colleges = list(session.exec(select(College).order_by(College.name)).all())
    rooms = list(session.exec(select(Auditorium)).all())
    today_bookings = list(
        session.exec(
            select(Booking).where(
                Booking.date == date_type.today(),
                Booking.status == "active",
            )
        ).all()
    )
    bookings_by_room = Counter(booking.room_id for booking in today_bookings)

    cards = []
    for college in colleges:
        college_rooms = [room for room in rooms if room.college_id == college.id]
        cards.append(
            {
                "college": college,
                "rooms": len(college_rooms),
                "available": sum(1 for room in college_rooms if room.is_available),
                "buildings": sorted({room.building for room in college_rooms}),
                "booked_today": sum(bookings_by_room.get(room.id, 0) for room in college_rooms),
                "capacity": sum(room.capacity for room in college_rooms),
            }
        )

    return render(
        request,
        "hub.html",
        user,
        cards=cards,
        total_rooms=len(rooms),
    )


@app.get("/college/{college_id}", response_class=HTMLResponse)
def college_map(
    college_id: int,
    request: Request,
    floor: Optional[int] = Query(None),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    college = session.get(College, college_id)
    if not college:
        flash(request, "Колледж не найден.", "error")
        return RedirectResponse("/hub", status_code=303)

    rooms = list(
        session.exec(
            select(Auditorium)
            .where(Auditorium.college_id == college_id)
            .order_by(Auditorium.floor, Auditorium.map_y, Auditorium.map_x)
        ).all()
    )
    floors = sorted({room.floor for room in rooms})
    selected_floor = floor if floor in floors else (floors[0] if floors else 1)
    floor_rooms = [room for room in rooms if room.floor == selected_floor]

    occupied_today: Counter = Counter()
    if floor_rooms:
        bookings = session.exec(
            select(Booking).where(
                Booking.date == date_type.today(),
                Booking.status == "active",
                Booking.room_id.in_([room.id for room in floor_rooms]),
            )
        ).all()
        occupied_today = Counter(booking.room_id for booking in bookings)

    return render(
        request,
        "college_map.html",
        user,
        college=college,
        rooms=floor_rooms,
        all_rooms_count=len(rooms),
        floors=floors,
        selected_floor=selected_floor,
        occupied_today=occupied_today,
    )


@app.get("/book", response_class=HTMLResponse)
def book_page(
    request: Request,
    room_id: int = Query(...),
    date: Optional[str] = Query(None),
    slot: int = Query(1, ge=1, le=7),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id)
    if not room:
        flash(request, "Аудитория не найдена.", "error")
        return RedirectResponse("/schedule", status_code=303)

    on_date = parse_date(date)
    if not user.can_book:
        flash(request, "Студенты могут только просматривать расписание.", "error")
        return RedirectResponse(f"/schedule?date={on_date.isoformat()}", status_code=303)

    occupied = [
        booking.time_slot
        for booking in session.exec(
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.date == on_date,
                Booking.status == "active",
            )
        ).all()
    ]

    if room.status != "available":
        flash(request, f"Аудитория {room.number} находится на ремонте.", "error")
        return RedirectResponse(f"/schedule?date={on_date.isoformat()}", status_code=303)
    if slot in occupied:
        flash(request, "Этот слот уже занят. Выберите другое время.", "error")
        return RedirectResponse(f"/schedule?date={on_date.isoformat()}", status_code=303)

    return render(
        request,
        "book.html",
        user,
        room=room,
        on_date=on_date,
        selected_slot=slot,
        occupied=occupied,
        errors=[],
        purpose="",
    )


@app.post("/book", response_class=HTMLResponse)
def book_submit(
    request: Request,
    room_id: int = Form(...),
    date: str = Form(...),
    time_slot: int = Form(...),
    purpose: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id)
    if not room:
        flash(request, "Аудитория не найдена.", "error")
        return RedirectResponse("/schedule", status_code=303)

    on_date = parse_date(date)
    errors = validate_booking(session, user, room, on_date, time_slot)

    if errors:
        occupied = [
            booking.time_slot
            for booking in session.exec(
                select(Booking).where(
                    Booking.room_id == room.id,
                    Booking.date == on_date,
                    Booking.status == "active",
                )
            ).all()
        ]
        return render(
            request,
            "book.html",
            user,
            status_code=400,
            room=room,
            on_date=on_date,
            selected_slot=time_slot,
            occupied=occupied,
            errors=errors,
            purpose=purpose,
        )

    booking = Booking(
        user_id=user.id,
        room_id=room.id,
        date=on_date,
        time_slot=time_slot,
        purpose=purpose.strip(),
    )
    session.add(booking)
    session.commit()

    slot = SLOT_BY_NUMBER[time_slot]
    flash(
        request,
        f"Аудитория {room.number} забронирована: {on_date.strftime('%d.%m.%Y')}, "
        f"{time_slot}-я пара ({slot['start']}–{slot['end']}).",
    )
    return RedirectResponse(f"/schedule?date={on_date.isoformat()}", status_code=303)


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    booking = session.get(Booking, booking_id)
    if not booking:
        flash(request, "Бронирование не найдено.", "error")
        return RedirectResponse("/my", status_code=303)

    if booking.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Можно отменять только свои бронирования.")

    if booking.status != "active":
        flash(request, "Эта бронь уже отменена.", "warning")
        return RedirectResponse(request.headers.get("referer") or "/my", status_code=303)

    booking.status = "cancelled"
    booking.cancelled_at = utcnow()
    session.add(booking)
    session.commit()
    flash(request, "Бронирование отменено, слот снова свободен.")
    return RedirectResponse(request.headers.get("referer") or "/my", status_code=303)


@app.get("/my", response_class=HTMLResponse)
def my_bookings(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    bookings = list(
        session.exec(
            select(Booking).where(Booking.user_id == user.id).order_by(Booking.date.desc(), Booking.time_slot)
        ).all()
    )
    rooms = {room.id: room for room in session.exec(select(Auditorium)).all()}
    items = [{"booking": booking, "room": rooms.get(booking.room_id)} for booking in bookings]

    upcoming = [
        item for item in items
        if item["booking"].status == "active" and item["booking"].date >= date_type.today()
    ]
    history = [item for item in items if item not in upcoming]
    return render(
        request,
        "my_bookings.html",
        user,
        upcoming=upcoming,
        history=history,
    )


# --------------------------------------------------------------------------
# Административная панель
# --------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_root(user: User = Depends(require_admin)):
    return RedirectResponse("/admin/rooms", status_code=303)


@app.get("/admin/rooms", response_class=HTMLResponse)
def admin_rooms(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    rooms = list(
        session.exec(
            select(Auditorium).order_by(Auditorium.college_id, Auditorium.building, Auditorium.number)
        ).all()
    )
    bookings = list(session.exec(select(Booking)).all())
    active_by_room: dict[int, int] = {}
    for booking in bookings:
        if booking.status == "active":
            active_by_room[booking.room_id] = active_by_room.get(booking.room_id, 0) + 1

    colleges = list(session.exec(select(College).order_by(College.name)).all())
    college_names = {college.id: college.short_name or college.name for college in colleges}

    return render(
        request,
        "admin_rooms.html",
        user,
        rooms=rooms,
        active_by_room=active_by_room,
        college_names=college_names,
    )


@app.get("/admin/rooms/new", response_class=HTMLResponse)
def admin_room_new(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    colleges = list(session.exec(select(College).order_by(College.name)).all())
    return render(
        request,
        "admin_room_form.html",
        user,
        room=None,
        selected_equipment=[],
        errors=[],
        colleges=colleges,
    )


@app.get("/admin/rooms/{room_id}/edit", response_class=HTMLResponse)
def admin_room_edit(
    room_id: int,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id)
    if not room:
        flash(request, "Аудитория не найдена.", "error")
        return RedirectResponse("/admin/rooms", status_code=303)
    colleges = list(session.exec(select(College).order_by(College.name)).all())
    return render(
        request,
        "admin_room_form.html",
        user,
        room=room,
        selected_equipment=room.equipment_list,
        errors=[],
        colleges=colleges,
    )


@app.post("/admin/rooms/save", response_class=HTMLResponse)
def admin_room_save(
    request: Request,
    room_id: Optional[int] = Form(None),
    college_id: Optional[int] = Form(None),
    number: str = Form(""),
    building: str = Form("Корпус A"),
    floor: int = Form(1),
    capacity: int = Form(20),
    equipment: list[str] = Form(default=[]),
    status: str = Form("available"),
    description: str = Form(""),
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id) if room_id else None
    colleges = list(session.exec(select(College).order_by(College.name)).all())
    errors: list[str] = []

    number = number.strip()
    college = session.get(College, college_id) if college_id else None
    if college is None:
        errors.append("Выберите колледж.")
    if not number:
        errors.append("Укажите номер аудитории.")
    if capacity < 1:
        errors.append("Вместимость должна быть больше нуля.")
    if not 1 <= floor <= 10:
        errors.append("Этаж должен быть в диапазоне 1–10.")
    if status not in ("available", "maintenance"):
        errors.append("Некорректный статус аудитории.")

    duplicate = session.exec(
        select(Auditorium).where(
            Auditorium.number == number,
            Auditorium.college_id == college_id,
        )
    ).first()
    if duplicate and (room is None or duplicate.id != room.id):
        errors.append(f"Аудитория с номером {number} уже есть в этом колледже.")

    if errors:
        return render(
            request,
            "admin_room_form.html",
            user,
            status_code=400,
            room=room,
            errors=errors,
            selected_equipment=equipment,
            colleges=colleges,
            form_data={
                "college_id": college_id,
                "number": number,
                "building": building,
                "floor": floor,
                "capacity": capacity,
                "description": description,
                "status": status,
            },
        )

    if room is None:
        room = Auditorium(number=number)
        session.add(room)

    room.college_id = college_id
    room.number = number
    room.building = building
    room.floor = floor
    room.capacity = capacity
    room.equipment = ", ".join(equipment)
    room.status = status
    room.description = description.strip()
    session.add(room)
    session.commit()

    flash(request, f"Аудитория {room.number} сохранена.")
    return RedirectResponse("/admin/rooms", status_code=303)


@app.post("/admin/rooms/{room_id}/delete")
def admin_room_delete(
    room_id: int,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id)
    if not room:
        flash(request, "Аудитория не найдена.", "error")
        return RedirectResponse("/admin/rooms", status_code=303)

    for booking in session.exec(select(Booking).where(Booking.room_id == room_id)).all():
        session.delete(booking)
    session.delete(room)
    session.commit()
    flash(request, f"Аудитория {room.number} удалена вместе со своими бронями.", "warning")
    return RedirectResponse("/admin/rooms", status_code=303)


@app.post("/admin/rooms/{room_id}/status")
def admin_room_status(
    room_id: int,
    request: Request,
    status: str = Form(...),
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    room = session.get(Auditorium, room_id)
    if not room:
        flash(request, "Аудитория не найдена.", "error")
        return RedirectResponse("/admin/rooms", status_code=303)

    room.status = "maintenance" if status == "maintenance" else "available"
    session.add(room)
    session.commit()
    flash(request, f"Статус аудитории {room.number}: {ROOM_STATUS_LABELS[room.status]}.")
    return RedirectResponse("/admin/rooms", status_code=303)


@app.get("/admin/bookings", response_class=HTMLResponse)
def admin_bookings(
    request: Request,
    date: Optional[str] = Query(None),
    status_filter: str = Query("", alias="status"),
    query: str = Query(""),
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    statement = select(Booking)
    on_date = parse_date(date) if date else None
    if on_date:
        statement = statement.where(Booking.date == on_date)
    if status_filter:
        statement = statement.where(Booking.status == status_filter)

    bookings = list(session.exec(statement.order_by(Booking.date.desc(), Booking.time_slot)).all())
    users = {item.id: item for item in session.exec(select(User)).all()}
    rooms = {item.id: item for item in session.exec(select(Auditorium)).all()}

    items = []
    needle = query.strip().lower()
    for booking in bookings:
        room = rooms.get(booking.room_id)
        owner = users.get(booking.user_id)
        if needle and needle not in (room.number.lower() if room else "") and needle not in (
            owner.username.lower() if owner else ""
        ):
            continue
        items.append({"booking": booking, "room": room, "owner": owner})

    return render(
        request,
        "admin_bookings.html",
        user,
        items=items,
        on_date=on_date,
        status_filter=status_filter,
        query=query,
    )


@app.get("/admin/report", response_class=HTMLResponse)
def admin_report(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    default_from, default_to = week_bounds(date_type.today())
    start = parse_date(date_from, default_from)
    end = parse_date(date_to, default_to)

    report = utilization_report(session, start, end)
    total_used = sum(item["used"] for item in report)
    average = round(sum(item["percent"] for item in report) / len(report), 1) if report else 0.0

    return render(
        request,
        "admin_report.html",
        user,
        report=report,
        date_from=start,
        date_to=end,
        total_used=total_used,
        average=average,
    )

"""Бизнес-логика: ConflictChecker, RoomFilter, построение сетки и отчётов."""

from collections import defaultdict
from datetime import date as date_type
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from .config import SLOT_BY_NUMBER, SLOTS_PER_DAY, TIME_SLOTS
from .models import Auditorium, Booking, User


class ConflictChecker:
    """Проверяет, не пересекается ли новая бронь с уже существующими.

    Атрибуты и метод соответствуют UML-диаграмме классов:
    booking_data, db_session, check_collision().
    """

    def __init__(self, db_session: Session, booking_data: Optional[dict] = None):
        self.db_session = db_session
        self.booking_data = booking_data or {}

    def check_collision(
        self,
        booking_data: Optional[dict] = None,
        exclude_id: Optional[int] = None,
    ) -> Optional[Booking]:
        """Вернуть конфликтующую активную бронь или None."""
        data = booking_data or self.booking_data
        room_id = data.get("room_id")
        on_date = data.get("date")
        time_slot = data.get("time_slot")
        if not room_id or not on_date or not time_slot:
            return None

        statement = select(Booking).where(
            Booking.room_id == room_id,
            Booking.date == on_date,
            Booking.time_slot == time_slot,
            Booking.status == "active",
        )
        if exclude_id is not None:
            statement = statement.where(Booking.id != exclude_id)
        return self.db_session.exec(statement).first()

    def has_conflict(
        self,
        room_id: int,
        on_date: date_type,
        time_slot: int,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """Удобная обёртка для проверки по отдельным параметрам."""
        return (
            self.check_collision(
                {"room_id": room_id, "date": on_date, "time_slot": time_slot},
                exclude_id=exclude_id,
            )
            is not None
        )


class RoomFilter:
    """Поисковый движок подбора аудиторий по критериям.

    Атрибуты и метод соответствуют UML: search_params, filters_list, apply_filters().
    """

    def __init__(self, db_session: Session, search_params: Optional[dict] = None):
        self.db_session = db_session
        self.search_params = search_params or {}
        self.filters_list: list[str] = []

    def apply_filters(self, **overrides) -> list[Auditorium]:
        """Отфильтровать аудитории по параметрам поиска."""
        params = {**self.search_params, **overrides}
        self.filters_list = []

        college_id = params.get("college_id")
        building = params.get("building") or ""
        min_capacity = params.get("min_capacity") or params.get("capacity") or None
        equipment = params.get("equipment") or ""
        query = (params.get("query") or "").strip().lower()
        include_maintenance = bool(params.get("include_maintenance"))

        rooms = list(
            self.db_session.exec(select(Auditorium).order_by(Auditorium.number)).all()
        )
        if not include_maintenance:
            rooms = [room for room in rooms if room.is_available]
            self.filters_list.append("только доступные")
        if college_id:
            rooms = [room for room in rooms if room.college_id == int(college_id)]
            self.filters_list.append(f"колледж №{college_id}")
        if building:
            rooms = [room for room in rooms if room.building == building]
            self.filters_list.append(f"корпус {building}")
        if min_capacity:
            rooms = [room for room in rooms if room.capacity >= int(min_capacity)]
            self.filters_list.append(f"мест ≥ {min_capacity}")
        if equipment:
            rooms = [room for room in rooms if equipment in room.equipment_list]
            self.filters_list.append(f"оборудование: {equipment}")
        if query:
            rooms = [
                room for room in rooms
                if query in room.number.lower() or query in room.description.lower()
            ]
            self.filters_list.append(f"поиск: {query}")

        return rooms


def validate_booking(
    session: Session,
    user: User,
    room: Auditorium,
    on_date: date_type,
    time_slot: int,
    exclude_id: Optional[int] = None,
) -> list[str]:
    """Полная проверка заявки. Возвращает список ошибок (пусто — всё ок)."""
    errors: list[str] = []

    if not user.can_book:
        errors.append("Студенты могут только просматривать расписание.")
    if room.status != "available":
        errors.append(f"Аудитория {room.number} находится на ремонте.")
    if time_slot not in SLOT_BY_NUMBER:
        errors.append("Некорректный номер пары.")
    if on_date < date_type.today():
        errors.append("Нельзя бронировать аудиторию на прошедшую дату.")

    conflict = ConflictChecker(session).check_collision(
        {"room_id": room.id, "date": on_date, "time_slot": time_slot},
        exclude_id=exclude_id,
    )
    if conflict:
        slot = SLOT_BY_NUMBER.get(conflict.time_slot, {})
        owner = session.get(User, conflict.user_id)
        errors.append(
            "Слот уже занят: пара {slot} ({start}–{end}), {owner}.".format(
                slot=conflict.time_slot,
                start=slot.get("start", ""),
                end=slot.get("end", ""),
                owner=owner.full_name if owner else "другой пользователь",
            )
        )
    return errors


def build_schedule(
    session: Session,
    rooms: list[Auditorium],
    on_date: date_type,
    current_user: User,
) -> list[dict]:
    """Собрать строки сетки «аудитория × пары» для шаблона."""
    rooms = list(rooms)
    if not rooms:
        return []

    bookings = list(
        session.exec(
            select(Booking).where(
                Booking.date == on_date,
                Booking.status == "active",
                Booking.room_id.in_([room.id for room in rooms]),
            )
        ).all()
    )
    users = {user.id: user for user in session.exec(select(User)).all()}
    by_cell: dict[tuple[int, int], Booking] = {
        (booking.room_id, booking.time_slot): booking for booking in bookings
    }

    rows = []
    for room in rooms:
        cells = []
        for slot in TIME_SLOTS:
            booking = by_cell.get((room.id, slot["number"]))
            if room.status != "available":
                state, label = "repair", "Ремонт"
            elif booking is None:
                state, label = "free", "Свободно"
            elif booking.user_id == current_user.id:
                state, label = "mine", "Моя бронь"
            else:
                state, label = "busy", "Занято"
            owner = users.get(booking.user_id) if booking else None
            cells.append(
                {
                    "slot": slot,
                    "state": state,
                    "label": label,
                    "booking": booking,
                    "owner": owner,
                    "can_book": state == "free" and current_user.can_book,
                }
            )
        rows.append({"room": room, "cells": cells})
    return rows


def utilization_report(
    session: Session,
    date_from: date_type,
    date_to: date_type,
) -> list[dict]:
    """Отчёт по загруженности фонда за период."""
    if date_to < date_from:
        date_from, date_to = date_to, date_from

    days = (date_to - date_from).days + 1
    total_slots = days * SLOTS_PER_DAY

    rooms = list(session.exec(select(Auditorium).order_by(Auditorium.number)).all())
    bookings = list(
        session.exec(
            select(Booking).where(
                Booking.date >= date_from,
                Booking.date <= date_to,
                Booking.status == "active",
            )
        ).all()
    )

    counters: dict[int, int] = defaultdict(int)
    for booking in bookings:
        counters[booking.room_id] += 1

    report = []
    for room in rooms:
        used = counters.get(room.id, 0)
        percent = round(used / total_slots * 100, 1) if total_slots else 0.0
        report.append(
            {
                "room": room,
                "used": used,
                "total": total_slots,
                "percent": percent,
            }
        )
    report.sort(key=lambda item: item["percent"], reverse=True)
    return report


def week_bounds(reference: date_type) -> tuple[date_type, date_type]:
    """Понедельник–воскресенье для недели, в которую попадает дата."""
    monday = reference - timedelta(days=reference.weekday())
    return monday, monday + timedelta(days=6)

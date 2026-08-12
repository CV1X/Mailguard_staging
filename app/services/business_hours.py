"""Calcul timp răspuns în ore/minute de lucru efectiv (business hours only).

Folosește department_schedule din DB: weekday ISO (1=luni..7=duminică), start_time, end_time.
Dacă emailul vine duminică la 12:00 și e preluat luni la 07:05, rezultatul e 5 minute, nu 19h.

Utilizare:
    schedule = load_schedule(cur, department='suport_1')
    minutes = business_minutes_between(received_at, sent_to_cts_at, schedule)
"""

from datetime import datetime, date, time, timedelta, timezone
from typing import List, Optional, Tuple


# Tipul unui interval de program: (weekday_iso 1-7, time_start, time_end)
ScheduleRow = Tuple[int, time, time]


def load_schedule(cur, department: str = "suport_1") -> List[ScheduleRow]:
    """Citește programul de lucru al unui departament din DB.

    Returnează lista de (weekday_iso, start_time, end_time) pentru zilele active.
    Dacă DB-ul nu e disponibil sau departamentul lipsește, returnează schedule default
    L-V 07:00-21:00 (suport_1 standard).
    """
    try:
        cur.execute(
            """
            SELECT weekday, start_time, end_time
            FROM department_schedule
            WHERE department = %s AND active = TRUE
            ORDER BY weekday
            """,
            (department,),
        )
        rows = cur.fetchall()
        if not rows:
            return _default_schedule()
        result = []
        for row in rows:
            if hasattr(row, "keys"):
                wd, ts, te = row["weekday"], row["start_time"], row["end_time"]
            else:
                wd, ts, te = row[0], row[1], row[2]
            result.append((int(wd), ts, te))
        return result
    except Exception:
        return _default_schedule()


def _default_schedule() -> List[ScheduleRow]:
    """Fallback: L-V 07:00–21:00 (corespunde suport_1)."""
    return [(d, time(7, 0), time(21, 0)) for d in range(1, 6)]


def _schedule_map(schedule: List[ScheduleRow]):
    """Convertește lista în dict {weekday_iso: (start_time, end_time)}."""
    return {wd: (ts, te) for wd, ts, te in schedule}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _minutes_in_day(dt_date: date, schedule_map: dict, start_limit: Optional[time] = None, end_limit: Optional[time] = None) -> float:
    """Minute de lucru disponibile într-o zi calendaristică, opțional limitate la un interval.

    weekday() returnează 0=luni..6=duminică; convertim la ISO 1=luni..7=duminică.
    """
    iso_wd = dt_date.isoweekday()  # 1=luni..7=duminică
    if iso_wd not in schedule_map:
        return 0.0  # zi liberă (weekend sau lipsă din schedule)

    ws, we = schedule_map[iso_wd]
    # Aplică limitele de interval dacă sunt date
    effective_start = max(ws, start_limit) if start_limit else ws
    effective_end = min(we, end_limit) if end_limit else we

    if effective_start >= effective_end:
        return 0.0

    delta = (
        datetime.combine(dt_date, effective_end)
        - datetime.combine(dt_date, effective_start)
    )
    return delta.total_seconds() / 60.0


def business_minutes_between(start: datetime, end: datetime, schedule: List[ScheduleRow]) -> float:
    """Calculează minutele de lucru efectiv între `start` și `end`.

    Ignoră orele din afara programului (noapte, weekend, zile fără schedule).
    Returnează 0.0 dacă end <= start sau dacă nicio zi din interval nu e lucrătoare.

    Algoritm:
    1. Prima zi: de la ora start până la end_of_day (sau end dacă e aceeași zi)
    2. Zilele intermediare: totalul zilei de lucru
    3. Ultima zi: de la start_of_day până la ora end (dacă e altă zi decât prima)
    """
    start = _to_utc(start)
    end = _to_utc(end)

    if end <= start:
        return 0.0

    smap = _schedule_map(schedule)
    total_minutes = 0.0

    current_date = start.date()
    end_date = end.date()

    while current_date <= end_date:
        if current_date == start.date() and current_date == end_date:
            # Același zi
            minutes = _minutes_in_day(
                current_date, smap,
                start_limit=start.time(),
                end_limit=end.time(),
            )
        elif current_date == start.date():
            # Prima zi: de la ora start până la end_of_day
            minutes = _minutes_in_day(
                current_date, smap,
                start_limit=start.time(),
                end_limit=None,
            )
        elif current_date == end_date:
            # Ultima zi: de la start_of_day până la ora end
            minutes = _minutes_in_day(
                current_date, smap,
                start_limit=None,
                end_limit=end.time(),
            )
        else:
            # Zi intermediară completă
            minutes = _minutes_in_day(current_date, smap)

        total_minutes += minutes
        current_date += timedelta(days=1)

    return total_minutes


def next_business_start(dt: datetime, schedule: List[ScheduleRow]) -> datetime:
    """Returnează primul moment de lucru >= dt.

    Util pentru a determina când ar fi trebuit să înceapă cronometrul de răspuns.
    Ex: duminică 12:00 → luni 07:00.
    """
    dt = _to_utc(dt)
    smap = _schedule_map(schedule)

    for offset in range(8):  # max 7 zile înainte (o săptămână)
        check_date = (dt + timedelta(days=offset)).date()
        iso_wd = check_date.isoweekday()
        if iso_wd not in smap:
            continue
        ws, _ = smap[iso_wd]
        candidate = datetime.combine(check_date, ws, tzinfo=timezone.utc)
        if candidate >= dt:
            return candidate
        if offset == 0:
            # Suntem în aceeași zi dar după start — verificăm dacă suntem încă în program
            _, we = smap[iso_wd]
            if dt.time() < we:
                return dt  # suntem deja în program
    return dt  # fallback

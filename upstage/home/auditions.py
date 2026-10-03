"""Productions with an audition still to come: the auditions pages and the auditions block both use these."""
from django.db.models import Min, Prefetch, Q
from django.utils import timezone

from backstage.models import Event, EventDateTime, Production

from .models import Block


def upcoming_auditions(production_id=None):
    """
    The productions that have an audition event with a date still to come, soonest first. Each has
    `audition_dates`: its upcoming audition dates, soonest first, as EventDateTimes (each with its event and venue), and
    `audition_days`: the days those fall on, each once (two audition times on one day are one day).
    With `production_id`, only that production (or nothing if it has no audition to come).
    """
    now = timezone.now()
    upcoming = Q(events__event_type=Event.EventType.AUDITION, events__datetimes__datetime__gte=now)
    productions = (
        Production.objects.filter(upcoming)
        .annotate(next_audition=Min("events__datetimes__datetime", filter=upcoming))
        .prefetch_related(
            "images__image",
            "team__person",
            "team__role",
            Prefetch(
                "events",
                queryset=Event.objects.filter(event_type=Event.EventType.AUDITION).select_related("venue").prefetch_related(
                    Prefetch("datetimes", queryset=EventDateTime.objects.filter(datetime__gte=now), to_attr="future_dates")
                ),
                to_attr="audition_events",
            ),
        )
        .order_by("next_audition", "title")
    )
    if production_id is not None:
        productions = productions.filter(pk=production_id)
    result = list(productions)
    for production in result:
        production.audition_dates = sorted(
            (date for event in production.audition_events for date in event.future_dates), key=lambda date: date.datetime
        )
        production.audition_days = list(dict.fromkeys(timezone.localtime(date.datetime).date() for date in production.audition_dates))
    return result


def audition_block(production):
    """The text for a production's audition view: a block named or titled "Audition: <production>", else "Audition"."""
    for label in (f"Audition: {production.title}", "Audition"):
        block = (
            Block.objects.filter(Q(name__iexact=label) | Q(title__iexact=label))
            .select_related("image", "production").order_by("id").first()
        )
        if block:
            return block
    return None


def audition_view(production):
    """Everything a production's audition view shows."""
    return {
        "production": production,
        "block": audition_block(production),
        "dates": production.audition_dates,
        "characters": production.cast.order_by("id"),
        "writers": [m.person for m in production.team.all() if m.role.name == "Writer"],
        "directors": [m.person for m in production.team.all() if m.role.name == "Director"],
    }

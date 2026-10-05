"""The diary block: productions with an audition and/or performance still to come, with the details of those events."""
from django.db.models import Min, Prefetch, Q
from django.utils import timezone

from backstage.models import Event, EventDateTime, Production

# Which types of event each choice of the block's "Show" option lists.
EVENT_TYPES = {
    "auditions": [Event.EventType.AUDITION],
    "performances": [Event.EventType.PERFORMANCE],
    "both": [Event.EventType.AUDITION, Event.EventType.PERFORMANCE],
}
SHOWN = [Event.Publish.PUBLISHED, Event.Publish.PROMOTED]


def diary_productions(show="both"):
    """
    The productions that have a published (or promoted) event of the chosen kind with a date still to come, soonest
    first. Each has `diary_events`: those events, soonest first, each with `future_dates` (its dates still to come, as
    EventDateTimes), its venue and ticket site.
    """
    now = timezone.now()
    types = EVENT_TYPES.get(show, EVENT_TYPES["both"])
    wanted = Q(events__event_type__in=types, events__publish__in=SHOWN, events__datetimes__datetime__gte=now)
    events = (
        Event.objects.filter(event_type__in=types, publish__in=SHOWN, datetimes__datetime__gte=now)
        .distinct()
        .select_related("venue", "ticket_site")
        .prefetch_related(Prefetch("datetimes", queryset=EventDateTime.objects.filter(datetime__gte=now), to_attr="future_dates"))
    )
    productions = (
        Production.objects.filter(wanted)
        .annotate(next_event=Min("events__datetimes__datetime", filter=wanted))
        .prefetch_related("images__image", Prefetch("events", queryset=events, to_attr="diary_events"))
        .order_by("next_event", "title")
    )
    result = list(productions)
    for production in result:
        production.diary_events.sort(key=lambda event: event.future_dates[0].datetime)
    return result

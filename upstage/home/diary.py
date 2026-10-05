"""The diary block: productions with events of the chosen kinds (recent or upcoming), with the details of those events."""
import calendar

from django.db.models import Prefetch, Q
from django.utils import timezone

from backstage.models import Event, EventDateTime, Production

RECENT_MONTHS = 6  # how far back "recent radio plays" goes


def months_ago(when, months):
    """The moment `months` calendar months before `when` (the day is kept, or the month's last day if it has no such day)."""
    index = when.year * 12 + when.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))
SHOWN = [Event.Publish.PUBLISHED, Event.Publish.PROMOTED]


def periods(shows, now):
    """{event type: (from, until)} for the chosen kinds; `until` is None for no end. Kinds of one type are merged."""
    wanted = {
        "recent_radio": (Event.EventType.BROADCAST, months_ago(now, RECENT_MONTHS), now),
        "upcoming_radio": (Event.EventType.BROADCAST, now, None),
        "upcoming_stage": (Event.EventType.PERFORMANCE, now, None),
        "auditions": (Event.EventType.AUDITION, now, None),
    }
    result = {}
    for show in shows:
        if show not in wanted:
            continue
        event_type, start, end = wanted[show]
        if event_type in result:
            old_start, old_end = result[event_type]
            start = min(start, old_start)
            end = None if end is None or old_end is None else max(end, old_end)
        result[event_type] = (start, end)
    return result


def diary_productions(shows=("upcoming_stage",)):
    """
    The productions that have a published (or promoted) event of any of the chosen kinds, earliest first: recent radio
    plays (broadcast in the last 6 months), upcoming radio plays, upcoming stage plays (performances) and auditions (the
    last three still to come). Each production has `diary_events`: its events of those kinds, earliest first, each with
    `dates` (its dates in the period, earliest first, as EventDateTimes), `upcoming` (it has a date still to come), and
    its venue and ticket site.
    """
    now = timezone.now()
    in_period = Q()
    for event_type, (start, end) in periods(shows, now).items():
        within = Q(datetime__gte=start) & (Q(datetime__lte=end) if end else Q())
        in_period |= Q(event__event_type=event_type) & within
    if not in_period:
        return []
    dates = (
        EventDateTime.objects.filter(in_period, event__publish__in=SHOWN)
        .select_related("event__venue", "event__ticket_site")
        .prefetch_related("event__productions")
        .order_by("datetime", "pk")
    )
    events = {}  # event id -> event, with its dates
    for date in dates:
        event = events.setdefault(date.event_id, date.event)
        if not hasattr(event, "dates"):
            event.dates = []
            event.upcoming = False
        event.dates.append(date)
        event.upcoming = event.upcoming or date.datetime >= now
    by_production = {}
    for event in events.values():  # already earliest first
        for production in event.productions.all():
            by_production.setdefault(production.pk, (production, []))[1].append(event)
    result = []
    images = Production.objects.filter(pk__in=by_production).prefetch_related("images__image")
    for production in images:
        production.diary_events = by_production[production.pk][1]
        production.first_date = production.diary_events[0].dates[0].datetime
        result.append(production)
    result.sort(key=lambda production: (production.first_date, production.title))
    return result

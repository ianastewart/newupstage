"""The promotion block: the promotion image of the next production to be performed."""
from django.db.models import Min, Q
from django.utils import timezone

from backstage.models import Event, EventDateTime, Image, Production


def next_performance():
    """
    The first production with a performance still to come: the one whose next performance (an event of type performance
    with a date in the future) is soonest. None if there isn't one. Ties go to the title.
    """
    upcoming = Q(events__event_type=Event.EventType.PERFORMANCE, events__datetimes__datetime__gte=timezone.now())
    return (
        Production.objects.filter(upcoming)
        .annotate(next_performance=Min("events__datetimes__datetime", filter=upcoming))
        .order_by("next_performance", "title", "pk")
        .first()
    )


def promotion_image(production):
    """
    A production's image of type promotion: its default image if that is a promotion image, else the first one added.
    None if it has none.
    """
    if production is None:
        return None
    link = (
        production.images.filter(image__image_type=Image.ImageType.PROMOTION)
        .select_related("image")
        .order_by("-is_default", "id")
        .first()
    )
    return link.image if link else None


def ticket_url(production):
    """
    Where to buy tickets for the production's next performance: the web address of the ticket site of the event that
    performance belongs to. Empty if there is no such performance, or its event has no ticket site or address.
    """
    if production is None:
        return ""
    date = (
        EventDateTime.objects.filter(
            event__productions=production, event__event_type=Event.EventType.PERFORMANCE, datetime__gte=timezone.now()
        )
        .select_related("event__ticket_site")
        .order_by("datetime", "pk")
        .first()
    )
    site = date.event.ticket_site if date else None
    return site.url if site and site.url else ""


def next_promotion():
    """What the promotion block shows: (the next performance's promotion image, its ticket address), or (None, "")."""
    production = next_performance()
    image = promotion_image(production)
    return (image, ticket_url(production)) if image else (None, "")

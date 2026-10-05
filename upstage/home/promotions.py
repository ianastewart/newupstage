"""The promotion block: the promotion image of the production of the next promoted event."""
from django.utils import timezone

from backstage.models import Event, EventDateTime, Image


def next_promoted_date():
    """
    The soonest date still to come of an event that is Promoted (whatever its type) and belongs to a production, with
    the event and its ticket site. None if there isn't one.
    """
    return (
        EventDateTime.objects.filter(
            event__publish=Event.Publish.PROMOTED, event__productions__isnull=False, datetime__gte=timezone.now()
        )
        .select_related("event__ticket_site")
        .order_by("datetime", "pk")
        .first()
    )


def promotion_image(production):
    """
    A production's image of type promotion: its default image if that is a promotion image, else the first one added.
    None if it has none.
    """
    link = (
        production.images.filter(image__image_type=Image.ImageType.PROMOTION)
        .select_related("image")
        .order_by("-is_default", "id")
        .first()
    )
    return link.image if link else None


def next_promotion():
    """
    What the promotion block shows: (the promotion image, the address to buy tickets) of the next promoted event, or
    (None, "") if no promoted event has a date to come, or its production has no promotion image. An event of several
    productions uses the first (by title) that has a promotion image. The tickets are those of the event's ticket site.
    """
    date = next_promoted_date()
    if date is None:
        return None, ""
    for production in date.event.productions.order_by("title", "pk"):
        if image := promotion_image(production):
            site = date.event.ticket_site
            return image, (site.url if site and site.url else "")
    return None, ""

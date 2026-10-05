from django.db import migrations

BROADCAST_VENUE = "Brooklands Radio"


def to_events(apps, schema_editor):
    """
    Every radio play with a listen address has a Broadcast event with that address: one that exists and has no address
    gets it, and a play with no Broadcast event gets a new, published one (at Brooklands Radio, if that venue exists;
    it has no date, as none is known).
    """
    Production = apps.get_model("backstage", "Production")
    Event = apps.get_model("backstage", "Event")
    Venue = apps.get_model("backstage", "Venue")
    venue = Venue.objects.filter(name=BROADCAST_VENUE).first()
    for production in Production.objects.filter(type="radio").exclude(listen_url__isnull=True).exclude(listen_url=""):
        events = list(production.events.filter(event_type="broadcast"))
        if not events:
            event = Event.objects.create(event_type="broadcast", publish="published", venue=venue, listen_url=production.listen_url)
            production.events.add(event)
        for event in events:
            if not event.listen_url:
                event.listen_url = production.listen_url
                event.save(update_fields=["listen_url"])


def to_production(apps, schema_editor):
    """Backwards: a production's listen address is that of its first Broadcast event that has one."""
    Production = apps.get_model("backstage", "Production")
    for production in Production.objects.all():
        event = production.events.filter(event_type="broadcast").exclude(listen_url="").order_by("id").first()
        if event:
            production.listen_url = event.listen_url
            production.save(update_fields=["listen_url"])


class Migration(migrations.Migration):

    dependencies = [
        ("backstage", "0021_event_listen_url"),
    ]

    operations = [
        migrations.RunPython(to_events, to_production),
    ]

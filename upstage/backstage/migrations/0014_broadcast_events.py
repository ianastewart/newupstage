from django.db import migrations


def broadcast_dates_to_events(apps, schema_editor):
    """Every production with a broadcast date gets a Broadcast event with that date, connected to it."""
    Production = apps.get_model("backstage", "Production")
    Event = apps.get_model("backstage", "Event")
    EventDateTime = apps.get_model("backstage", "EventDateTime")
    for production in Production.objects.exclude(broadcast_datetime=None):
        already = EventDateTime.objects.filter(
            event__productions=production, event__event_type="broadcast", datetime=production.broadcast_datetime
        ).exists()
        if already:  # (so that running this again does not make a second one)
            continue
        event = Event.objects.create(title=f"{production.title} broadcast"[:255], event_type="broadcast")
        EventDateTime.objects.create(event=event, datetime=production.broadcast_datetime)
        production.events.add(event)


def events_to_broadcast_dates(apps, schema_editor):
    """Going back: a production's broadcast date is the first date of its broadcast events; those events are removed."""
    Production = apps.get_model("backstage", "Production")
    Event = apps.get_model("backstage", "Event")
    EventDateTime = apps.get_model("backstage", "EventDateTime")
    for production in Production.objects.filter(events__event_type="broadcast").distinct():
        first = (
            EventDateTime.objects.filter(event__productions=production, event__event_type="broadcast")
            .order_by("datetime").first()
        )
        if first:
            production.broadcast_datetime = first.datetime
            production.save(update_fields=["broadcast_datetime"])
    Event.objects.filter(event_type="broadcast").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("backstage", "0013_event_type_broadcast"),
    ]

    operations = [
        migrations.RunPython(broadcast_dates_to_events, events_to_broadcast_dates),
    ]

from django.contrib.auth.decorators import login_not_required
from django.db.models import F, Min, Q, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from backstage.models import Event, EventDateTime, Person, Production
from backstage.views import person_productions

from .forms import BlockForm, WebPageForm
from .models import Block, WebPage


@login_not_required
def home(request):
    return render(request, "home/home.html")


@login_not_required
def webpage(request, slug):
    """A page built from its blocks, in order."""
    page = get_object_or_404(WebPage, slug=slug)
    page_blocks = list(page.page_blocks())
    # The page's first hero image block goes in the base template's hero area, above the content.
    hero = next((pb.block for pb in page_blocks if pb.block.block_type == Block.BlockType.HERO_IMAGE), None)
    content_blocks = [pb for pb in page_blocks if pb.block != hero]
    return render(request, "home/webpage.html", {"page": page, "hero": hero, "page_blocks": content_blocks})


def public_actors():
    """The actors shown on the public site: people with the Actor role who have a photo."""
    return Person.objects.filter(roles__name="Actor", image__isnull=False).select_related("image").distinct()


@login_not_required
def actor_list(request):
    """The public actors page: a grid of photos and names, alphabetical by surname."""
    # People known by one name ("Divya") sort by that name.
    actors = public_actors().order_by(
        Coalesce(NullIf(Lower("last_name"), Value("")), Lower("first_name")), Lower("first_name")
    )
    return render(request, "home/actor_list.html", {"actors": actors})


@login_not_required
def actor_detail(request, pk):
    """One actor's public page: name, photo and biography only."""
    person = get_object_or_404(public_actors(), pk=pk)
    cast_in, credits = person_productions(person)
    return render(request, "home/actor_detail.html", {"person": person, "cast_in": cast_in, "credits": credits})


def radio_plays():
    """Every production that is a radio play, latest broadcast first (those with no date last)."""
    return Production.objects.filter(type=Production.ProductionType.RADIO).prefetch_related("images__image").order_by(
        F("broadcast_datetime").desc(nulls_last=True), "title"
    )


@login_not_required
def radio_archive(request):
    """The public radio archive: each radio play's image and title, latest first."""
    return render(request, "home/radio_archive.html", {"plays": radio_plays()})


@login_not_required
def radio_play(request, pk):
    """One radio play: a bigger image, the writer, the rest of the production team and the cast."""
    play = get_object_or_404(radio_plays().prefetch_related("cast__actor", "team__person", "team__role"), pk=pk)
    # The writer has their own line, so the team list leaves them out.
    team = sorted(
        (member for member in play.team.all() if member.role.name != "Writer"),
        key=lambda member: (member.role.name, member.person.last_name, member.person.first_name),
    )
    cast = sorted(play.cast.all(), key=lambda part: part.id)
    return render(request, "home/radio_play.html", {"play": play, "team": team, "cast": cast})


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


@login_not_required
def auditions(request):
    """Every production with an audition still to come, soonest first, each in its audition view."""
    now = timezone.now()
    upcoming = Q(events__event_type=Event.EventType.AUDITION, events__datetimes__datetime__gte=now)
    productions = (
        Production.objects.filter(upcoming)
        .annotate(next_audition=Min("events__datetimes__datetime", filter=upcoming))
        .prefetch_related("images__image", "team__person", "team__role")
        .order_by("next_audition", "title")
    )
    audition_views = []
    for production in productions:
        # Each upcoming audition date, with its event (for the venue).
        dates = (
            EventDateTime.objects.filter(
                event__productions=production, event__event_type=Event.EventType.AUDITION, datetime__gte=now
            )
            .select_related("event__venue")
            .order_by("datetime")
        )
        audition_views.append({
            "production": production,
            "block": audition_block(production),
            "dates": dates,
            "characters": production.cast.order_by("id"),
            "writers": [m.person for m in production.team.all() if m.role.name == "Writer"],
            "directors": [m.person for m in production.team.all() if m.role.name == "Director"],
        })
    return render(request, "home/auditions.html", {"audition_views": audition_views})


def page_list(request):
    return render(request, "home/page_list.html", {"pages": WebPage.objects.all()})


def page_create(request):
    """Create a page (title and slug), then build it in the page editor."""
    form = WebPageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        page = form.save()
        return redirect("page-edit", pk=page.pk)
    return render(request, "home/page_form.html", {"form": form})


def page_edit(request, pk):
    """
    Build a page: its blocks in order, each with move up / move down / remove,
    plus adding a new or existing block, and editing the title and slug.
    """
    page = get_object_or_404(WebPage, pk=pk)
    form = WebPageForm(instance=page)

    if request.method == "POST":
        action = request.POST.get("action")
        page_block_id = request.POST.get("page_block", "")
        page_block_id = int(page_block_id) if page_block_id.isdigit() else None
        anchor = ""
        if action == "details":
            form = WebPageForm(request.POST, instance=page)
            if form.is_valid():
                form.save()
                return redirect("page-edit", pk=page.pk)
        else:
            if action in ("up", "down") and page_block_id:
                page.move_block(page_block_id, -1 if action == "up" else 1)
                anchor = f"#page-block-{page_block_id}"
            elif action == "remove" and page_block_id:
                page.remove_block(page_block_id)
            elif action == "add_existing":
                block_id = request.POST.get("block", "")
                if block_id.isdigit() and (block := Block.objects.filter(pk=block_id).first()):
                    anchor = f"#page-block-{page.add_block(block).pk}"
            return redirect(reverse("page-edit", args=[page.pk]) + anchor)

    page_blocks = list(page.page_blocks())
    return render(request, "home/page_edit.html", {
        "page": page,
        "form": form,
        "page_blocks": page_blocks,
        # Blocks can be shared between pages: offer the ones not already on this page.
        "other_blocks": Block.objects.exclude(pk__in=[pb.block_id for pb in page_blocks]),
    })


def block_create(request, page_pk):
    """Add a new block to the end of a page."""
    page = get_object_or_404(WebPage, pk=page_pk)
    form = BlockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        page_block = page.add_block(form.save())
        return redirect(reverse("page-edit", args=[page.pk]) + f"#page-block-{page_block.pk}")
    return render(request, "home/block_form.html", {"form": form, "page": page})


def block_edit(request, page_pk, pk):
    """Edit a block (changes show on every page that uses it), then return to the page editor."""
    page = get_object_or_404(WebPage, pk=page_pk)
    block = get_object_or_404(Block, pk=pk)
    form = BlockForm(request.POST or None, instance=block)
    if request.method == "POST" and form.is_valid():
        form.save()
        page_block = page.pageblock_set.filter(block=block).first()
        return redirect(reverse("page-edit", args=[page.pk]) + (f"#page-block-{page_block.pk}" if page_block else ""))
    return render(request, "home/block_form.html", {
        "form": form, "page": page, "block": block,
        "other_pages": block.pages.exclude(pk=page.pk),
    })

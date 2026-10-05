from django.contrib.auth.decorators import login_not_required
from django.db.models import F, Min, Q, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from backstage.forms import ContactForm
from backstage.models import Event, EventDateTime, Person, Production
from backstage.views import person_productions

from .auditions import audition_view, upcoming_auditions
from .promotions import production_ticket_url, production_venue, promotion_image
from .forms import BlockColumnFormSet, BlockForm, WebPageForm
from .models import Block, WebPage


@login_not_required
def home(request):
    return webpage(request, "home")


@login_not_required
def webpage(request, slug):
    """A page built from its blocks, in order."""
    slug = slug or 'home'
    page = get_object_or_404(WebPage, slug=slug)
    page_blocks = list(page.page_blocks())
    # The page's first hero image block goes in the base template's hero area, above the content.
    hero = next((pb.block for pb in page_blocks if pb.block.block_type == Block.BlockType.HERO_IMAGE), None)
    content_blocks = [pb for pb in page_blocks if pb.block != hero]
    context = {"page": page, "hero": hero, "page_blocks": content_blocks}
    if request.method == "POST":
        # A contact block's form: the block it came from is posted with it.
        block_id = request.POST.get("contact_block", "")
        block = next((pb.block for pb in page_blocks if str(pb.block.pk) == block_id and pb.block.block_type == Block.BlockType.CONTACT), None)
        if block is None:
            raise Http404
        form = ContactForm(request.POST)
        if form.is_valid():
            if not form.is_spam:
                form.save()
            return redirect(f"{request.path}?sent={block.pk}#contact-{block.pk}")
        context.update(contact_block=block.pk, contact_form=form)
    elif request.GET.get("sent", "").isdigit():
        context["contact_sent"] = int(request.GET["sent"])
    return render(request, "home/webpage.html", context)


def public_actors():
    """The actors shown on the public site: people with the Actor role who have a photo."""
    return Person.objects.filter(roles__name="Actor", image__isnull=False).select_related("image").distinct()


def public_team_members():
    """The non-actors shown on the public site: people credited on a production team who have a photo or a biography."""
    return (
        Person.objects.filter(productionteam__isnull=False)
        .exclude(pk__in=public_actors().values("pk"))
        .filter(Q(image__isnull=False) | ~Q(biography=""))
        .select_related("image")
        .distinct()
    )


def return_production(request):
    """The production a person's page was opened from (?production=<pk>), for its back link; None otherwise."""
    pk = request.GET.get("production", "")
    return Production.objects.filter(pk=pk).first() if pk.isdigit() else None


def with_public_urls(people, production=None):
    """Give each person (in `people`, any with the same person more than once) `public_url`: their public page, or ""."""
    actors = set(public_actors().values_list("pk", flat=True))
    team = set(public_team_members().values_list("pk", flat=True))
    for person in people:
        if person is None:
            continue
        if person.pk in actors:
            person.public_url = reverse("public-actor", args=[person.pk])
        elif person.pk in team:
            person.public_url = reverse("public-team-member", args=[person.pk])
        else:
            person.public_url = ""
        if person.public_url and production:
            person.public_url += f"?production={production.pk}"  # so the person's page can go back to it


@login_not_required
def team_member_detail(request, pk):
    """One production team member's public page (someone who is not a public actor): name, photo, biography and credits."""
    person = get_object_or_404(public_team_members(), pk=pk)
    cast_in, credits = person_productions(person)
    return render(
        request, "home/actor_detail.html",
        {"person": person, "cast_in": cast_in, "credits": credits, "back_production": return_production(request)},
    )


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
    return render(
        request, "home/actor_detail.html",
        {"person": person, "cast_in": cast_in, "credits": credits, "back_to_actors": True, "back_production": return_production(request)},
    )


def radio_plays():
    """Every production that is a radio play, latest broadcast first (those with no date last)."""
    return (
        Production.objects.filter(type=Production.ProductionType.RADIO)
        .with_broadcast_date()
        .prefetch_related("images__image")
        .order_by(F("broadcast_at").desc(nulls_last=True), "title")
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


@login_not_required
def public_production(request, pk):
    """
    One production's public page. With a promotion image, that image with the Buy Tickets (or Listen) button on it;
    without, a card like the cast list block's: the production's image and cast, with the button. The production team
    is shown either way.
    """
    production = get_object_or_404(
        Production.objects.prefetch_related("images__image", "cast__actor", "team__person", "team__role"), pk=pk
    )
    team = sorted(
        production.team.all(), key=lambda member: (member.role.name, member.person.last_name, member.person.first_name)
    )
    cast = sorted(production.cast.all(), key=lambda part: part.id)
    # The people with a public page (see public_actors and public_team_members) are linked to it.
    with_public_urls([member.person for member in team] + [part.actor for part in cast], production)
    return render(request, "home/production_detail.html", {
        "production": production,
        "promotion_image": promotion_image(production),
        "ticket_url": production_ticket_url(production),
        "venue": production_venue(production),
        "team": team,
        "cast": cast,
    })


@login_not_required
def auditions(request):
    """Every production with an audition still to come, soonest first, each in its audition view."""
    return render(request, "home/auditions.html", {"audition_views": [audition_view(p) for p in upcoming_auditions()]})


@login_not_required
def event_detail(request, pk):
    """One event's public page: what it is, where, every date, who it is for and how to get tickets. Published events only."""
    event = get_object_or_404(
        Event.objects.filter(publish__in=[Event.Publish.PUBLISHED, Event.Publish.PROMOTED])
        .select_related("venue__logo", "ticket_site")
        .prefetch_related("datetimes", "productions__images__image"),
        pk=pk,
    )
    now = timezone.now()
    dates = list(event.datetimes.all())
    return render(request, "home/event_detail.html", {
        "event": event,
        "dates": dates,
        "productions": sorted(event.productions.all(), key=lambda production: production.title),
        "upcoming": any(date.datetime >= now for date in dates),
    })


@login_not_required
def audition_detail(request, pk):
    """One production's audition view: its dates, who is wanted and what for. Only while an audition is still to come."""
    productions = upcoming_auditions(pk)
    if not productions:
        raise Http404("This production has no audition coming up.")
    return render(request, "home/audition_detail.html", {"view": audition_view(productions[0])})


def page_list(request):
    return render(request, "home/page_list.html", {"pages": WebPage.objects.all()})


def page_copy(request, pk):
    """Copy a page (POST): the copy is the page's name with (copy) added, and opens in the page editor."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return redirect("page-edit", pk=get_object_or_404(WebPage, pk=pk).copy().pk)


def page_replace_original(request, pk):
    """
    A copied page takes the place of its original (POST). `delete_page` deletes the original, and then `delete_blocks`
    deletes its blocks too; if the original is kept, it and its blocks are renamed with (old).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    page = get_object_or_404(WebPage, pk=pk)
    delete_page = bool(request.POST.get("delete_page"))
    page.replace_original(delete_page, delete_blocks=delete_page and bool(request.POST.get("delete_blocks")))
    return redirect("page-edit", pk=page.pk)


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


def _save_block(request, block=None):
    """
    The block form and its columns formset, bound to the POST if there is one. Returns (form, formset, saved block
    or None). The columns are only checked and saved for the types of block that have columns.
    """
    form = BlockForm(request.POST or None, instance=block)
    formset = BlockColumnFormSet(request.POST or None, instance=block or Block(), prefix="col")
    if request.method != "POST":
        return form, formset, None
    columns = 0
    if form.is_valid():
        columns = Block.COLUMN_COUNTS.get(form.cleaned_data["block_type"], 0)
        formset.required_columns = columns
    if form.is_valid() and (not columns or formset.is_valid()):
        saved = form.save()
        if columns:
            formset.instance = saved
            formset.save_columns(saved)
        return form, formset, saved
    return form, formset, None


def block_create(request, page_pk):
    """Add a new block to the end of a page."""
    page = get_object_or_404(WebPage, pk=page_pk)
    form, formset, block = _save_block(request)
    if block:
        page_block = page.add_block(block)
        return redirect(reverse("page-edit", args=[page.pk]) + f"#page-block-{page_block.pk}")
    return render(request, "home/block_form.html", {"form": form, "formset": formset, "page": page})


def block_edit(request, page_pk, pk):
    """Edit a block (changes show on every page that uses it), then return to the page editor."""
    page = get_object_or_404(WebPage, pk=page_pk)
    block = get_object_or_404(Block, pk=pk)
    form, formset, saved = _save_block(request, block)
    if saved:
        page_block = page.pageblock_set.filter(block=block).first()
        return redirect(reverse("page-edit", args=[page.pk]) + (f"#page-block-{page_block.pk}" if page_block else ""))
    return render(request, "home/block_form.html", {
        "form": form, "formset": formset, "page": page, "block": block,
        "other_pages": block.pages.exclude(pk=page.pk),
    })

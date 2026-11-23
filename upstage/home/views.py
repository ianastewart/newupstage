from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db.models import Exists, F, Min, OuterRef, Q, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from django.views.decorators.clickjacking import xframe_options_sameorigin

from backstage.forms import ContactForm
from backstage.models import Event, EventDateTime, ParentProduction, Person, Production, Role, team_sort_key
from backstage.views import person_productions

from .auditions import audition_view, upcoming_auditions
from .promotions import production_ticket_url, production_venue, promotion_image
from .seo import seo
from .forms import BlockColumnFormSet, BlockForm, WebPageForm
from .models import Block, WebPage


@login_not_required
def home(request):
    return webpage(request, "home")


# The blocks whose text can describe the page.
SEO_TEXT_BLOCKS = (Block.BlockType.TEXT, Block.BlockType.TEXT_IMAGE, Block.BlockType.SPLIT, Block.BlockType.HERO_IMAGE)


@login_not_required
def robots_txt(request):
    """What search engines may crawl: the public pages, not the backstage ones; and where the sitemap is."""
    if settings.SITE_MODE == "sandbox":
        return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
    lines = [
        "User-agent: *",
        "Disallow: /backstage/",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /pages/",  # the page editor
        "",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def person_seo(request, person):
    """The tags for a person's public page: their biography is the description, their photo the image."""
    return seo(request, title=str(person).strip(), description=person.biography, image=person.image, og_type="profile")


def production_image(production):
    """The image that stands for a production in link previews: the one chosen for its public page, else its promotion
    image, else its default image."""
    if production.public_image_id:
        return production.public_view_image
    link = production.default_image
    return promotion_image(production) or (link.image if link else None)


@login_not_required
def webpage(request, slug):
    """A page built from its blocks, in order."""
    slug = slug or 'home'
    page = get_object_or_404(WebPage, slug=slug, production__isnull=True)  # a production's blocks are on its own page
    page_blocks = list(page.page_blocks())
    # The page's first hero image block goes in the base template's hero area, above the content.
    hero = next((pb.block for pb in page_blocks if pb.block.block_type == Block.BlockType.HERO_IMAGE), None)
    content_blocks = [pb for pb in page_blocks if pb.block != hero]
    context = {"page": page, "hero": hero, "page_blocks": content_blocks}
    text_block = next((pb.block for pb in page_blocks if pb.block.text and pb.block.block_type in SEO_TEXT_BLOCKS), None)
    image_block = hero or next((pb.block for pb in page_blocks if pb.block.image_id), None)
    context["seo"] = seo(
        request,
        title="" if page.slug == "home" else page.title,
        description=text_block.text if text_block else "",
        image=image_block.image if image_block else None,
        noindex=page.copied_from_id is not None,  # a copy still being worked on
        canonical_path=reverse("home") if page.slug == "home" else None,  # the home page is the site's root
    )
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
        {"person": person, "cast_in": cast_in, "credits": credits, "back_production": return_production(request),
         "seo": person_seo(request, person)},
    )


def public_people_ordering():
    # People known by one name ("Divya") sort by that name.
    return Coalesce(NullIf(Lower("last_name"), Value("")), Lower("first_name")), Lower("first_name")


def public_people_page(request, people, title, description, empty):
    """A grid of people's photos and names (initials for those with no photo), each linked to their public page."""
    people = list(people)
    with_public_urls(people)
    return render(request, "home/people_list.html", {
        "people": people, "title": title, "empty": empty,
        "seo": seo(request, title=title, description=description),
    })


@login_not_required
def writer_list(request):
    """The public writers page: everyone with the Writer role who has a public page (a photo or a biography)."""
    writers = (
        Person.objects.filter(roles__name="Writer").filter(Q(image__isnull=False) | ~Q(biography=""))
        .select_related("image").distinct().order_by(*public_people_ordering())
    )
    return public_people_page(request, writers, "Writers", "The writers of Upstage Surrey.", "No writers to show yet.")


@login_not_required
def crew_list(request):
    """The public crew page: everyone with a role other than Actor or Writer (linked to their page where they have one)."""
    crew = (
        Person.objects.filter(roles__in=Role.objects.exclude(name__in=["Actor", "Writer"]))
        .select_related("image").distinct().order_by(*public_people_ordering())
    )
    return public_people_page(request, crew, "Crew", "The crew of Upstage Surrey.", "No crew to show yet.")


def production_type_list(request, production_type, title, empty, dated=False):
    """
    The public page for one type of production: each one's image and title, linked to its page (a parent production, the
    evening that groups several plays, is left out: its plays are listed). With `dated`, newest
    first by the date of the first published performance or broadcast (shown under the image as month and year);
    productions with no date come last. Otherwise alphabetical.
    """
    productions = (
        Production.objects.filter(type=production_type)
        .filter(~Exists(ParentProduction.objects.filter(pk=OuterRef("pk"))))  # the plays of an evening, not the evening
        .prefetch_related("images__image")
    )
    if dated:
        shown = [Event.EventType.PERFORMANCE, Event.EventType.BROADCAST]
        productions = productions.annotate(
            show_date=Min(
                "events__datetimes__datetime",
                filter=Q(events__event_type__in=shown, events__publish__in=Event.SHOWN),
            )
        ).order_by(F("show_date").desc(nulls_last=True), F("parent_id").asc(nulls_first=True), "title")
    else:
        productions = productions.order_by("title")
    return render(request, "home/production_grid.html", {
        "productions": productions, "title": title, "empty": empty,
        "seo": seo(request, title=title, description=f"{title} from Upstage Surrey."),
    })


@login_not_required
def stage_shows(request):
    return production_type_list(
        request, Production.ProductionType.STAGE, "Stage shows", "No stage shows to show yet.", dated=True
    )


@login_not_required
def musicals(request):
    return production_type_list(
        request, Production.ProductionType.MUSICAL, "Musicals", "No musicals to show yet.", dated=True
    )


@login_not_required
def films(request):
    return production_type_list(request, Production.ProductionType.FILM, "Films", "No films to show yet.")


@login_not_required
def actor_list(request):
    """The public actors page: a grid of photos and names, alphabetical by surname."""
    # People known by one name ("Divya") sort by that name.
    actors = public_actors().order_by(
        Coalesce(NullIf(Lower("last_name"), Value("")), Lower("first_name")), Lower("first_name")
    )
    return render(request, "home/actor_list.html", {
        "actors": actors,
        "seo": seo(request, title="Actors", description="The actors of Upstage Surrey."),
    })


@login_not_required
def actor_detail(request, pk):
    """One actor's public page: name, photo and biography only."""
    person = get_object_or_404(public_actors(), pk=pk)
    cast_in, credits = person_productions(person)
    return render(
        request, "home/actor_detail.html",
        {"person": person, "cast_in": cast_in, "credits": credits, "back_to_actors": True,
         "back_production": return_production(request), "seo": person_seo(request, person)},
    )


def cast_by_actor_name(cast):
    """A cast list sorted by the actors' first names, then surnames; parts with no actor go last, in the order they were added."""
    return sorted(
        cast,
        key=lambda part: (
            part.actor is None,
            (part.actor.first_name.lower(), part.actor.last_name.lower()) if part.actor else ("", ""),
            part.id,
        ),
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
    plays = radio_plays()
    query = request.GET.get("q", "").strip()
    if query:
        # Every word must match the title, strap line or the name of someone in the cast or team.
        for word in query.split():
            plays = plays.filter(
                Q(title__icontains=word) | Q(strap_line__icontains=word)
                | Q(cast__actor__first_name__icontains=word) | Q(cast__actor__last_name__icontains=word)
                | Q(team__person__first_name__icontains=word) | Q(team__person__last_name__icontains=word)
            )
        plays = plays.distinct()
    return render(request, "home/radio_archive.html", {
        "plays": plays,
        "query": query,
        "seo": seo(request, title="Radio archive", description="Listen to the radio plays from Upstage Surrey."),
    })


# The parts of a production's public page that the backstage Public view tab can switch off.
PUBLIC_VIEW_PARTS = ("title", "strap_line", "description", "venue_logo", "cast", "team")


def public_view_options(request, production):
    """
    Which parts of a production's public page to show: those not switched off on its backstage Public view tab. A
    request with `custom` (the tab's preview) shows only the parts named by its `show` values instead.
    """
    if "custom" not in request.GET:
        return {part: part not in production.public_hidden_parts for part in PUBLIC_VIEW_PARTS}
    chosen = set(request.GET.getlist("show"))
    return {part: part in chosen for part in PUBLIC_VIEW_PARTS}


@login_not_required
@xframe_options_sameorigin  # the backstage Public view tab shows it in a frame
def public_production(request, pk):
    """
    One production's public page: its title, strap line and description, the image chosen on the backstage Public view
    tab (else the default image) with the Buy Tickets (or Listen) button under it, then the cast and the team.
    """
    production = get_object_or_404(
        Production.objects.prefetch_related("images__image", "cast__actor", "team__person", "team__role"), pk=pk
    )
    production.find_listen_url(cached=True)
    ticket_url = production_ticket_url(production)
    show = public_view_options(request, production)
    # A radio play's cast is kept back until it has a broadcast date.
    awaiting_date = production.type == Production.ProductionType.RADIO and production.broadcast_datetime is None
    if awaiting_date:
        show["cast"] = False
    team = sorted(production.team.all(), key=team_sort_key)
    cast = cast_by_actor_name(production.cast.all())
    # The people with a public page (see public_actors and public_team_members) are linked to it.
    with_public_urls([member.person for member in team] + [part.actor for part in cast], production)
    # The blocks added to the production's public page (a contact form is not offered here: nothing receives it).
    page = WebPage.objects.filter(production=production).first()
    page_blocks = [
        pb for pb in (page.page_blocks() if page else [])
        if pb.block.block_type != Block.BlockType.CONTACT
    ]
    return render(request, "home/production_detail.html", {
        "production": production,
        "page_blocks": page_blocks,
        "image": production.public_view_image,
        "show": show,
        "awaiting_date": awaiting_date,
        # The Radio plays menu item is highlighted on a radio play's page.
        "nav_section": "radio-archive" if production.type == Production.ProductionType.RADIO else "",
        # The backstage Public view shows just the page's contents, the whole image fitting the window if it can.
        "bare": "custom" in request.GET,
        "base_template": "public_bare.html" if "custom" in request.GET else "public_base.html",
        "ticket_url": ticket_url,
        # The Listen now button is only offered when there is no Buy Tickets one.
        "listen_url": "" if ticket_url else production.public_listen_url,
        "venue": production_venue(production),
        "team": team,
        "cast": cast,
        "seo": seo(
            request, title=production.title, description=production.description, image=production_image(production),
        ),
    })


@login_not_required
def auditions(request):
    """Every production with an audition still to come, soonest first, each in its audition view."""
    return render(request, "home/auditions.html", {
        "audition_views": [audition_view(p) for p in upcoming_auditions()],
        "seo": seo(request, title="Auditions", description="Auditions coming up with Upstage Surrey."),
    })


@login_not_required
def event_detail(request, pk):
    """One event's public page: what it is, where, every date, who it is for and how to get tickets. Published events only."""
    event = get_object_or_404(
        Event.objects.published()
        .select_related("venue__logo", "ticket_site")
        .prefetch_related("datetimes", "productions__images__image"),
        pk=pk,
    )
    now = timezone.now()
    dates = list(event.datetimes.all())
    productions = sorted(event.productions.all(), key=lambda production: production.title)
    first = productions[0] if productions else None
    return render(request, "home/event_detail.html", {
        "event": event,
        "dates": dates,
        "productions": productions,
        "upcoming": any(date.datetime >= now for date in dates),
        "seo": seo(
            request,
            title=" and ".join(production.title for production in productions) or event.get_event_type_display(),
            description=event.description or (first.description if first else ""),
            image=production_image(first) if first else None,
        ),
    })


@login_not_required
def audition_detail(request, pk):
    """One production's audition view: its dates, who is wanted and what for. Only while an audition is still to come."""
    productions = upcoming_auditions(pk)
    if not productions:
        raise Http404("This production has no audition coming up.")
    production = productions[0]
    return render(request, "home/audition_detail.html", {
        "view": audition_view(production),
        "seo": seo(
            request, title=f"{production.title} auditions", description=production.description,
            image=production_image(production),
        ),
    })


def page_list(request):
    return render(request, "home/page_list.html", {"pages": WebPage.objects.filter(production__isnull=True)})


def page_copy(request, pk):
    """Copy a page (POST): the copy is the page's name with (copy) added, and opens in the page editor."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return redirect("page-edit", pk=get_object_or_404(WebPage, pk=pk).copy().pk)


def page_delete(request, pk):
    """Delete a page (POST). Its blocks are kept, unless `delete_blocks` is ticked (blocks on another page are always kept)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    page = get_object_or_404(WebPage, pk=pk)
    if request.POST.get("delete_blocks"):
        page.delete_with_blocks()
    else:
        page.delete()
    return redirect("page-list")


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


def production_page_edit(request, pk):
    """Edit the blocks on a production's public page: its page of blocks (made when first wanted) in the page editor."""
    production = get_object_or_404(Production, pk=pk)
    return redirect("page-edit", pk=WebPage.for_production(production).pk)


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

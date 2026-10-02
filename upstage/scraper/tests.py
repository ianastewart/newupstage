from unittest import TestCase

from scraper.scrape import (
    _split_title_date, brooklands_plays, find_brooklands_play, parse_brooklands_blurb, parse_brooklands_play,
    parse_brooklands_cast, parse_brooklands_credits, print_brooklands_plays,
)

# Two entries as the Brooklands Radio Playhouse list shows them.
SAMPLE_LIST = """
<ol class="search_list">
<b><u>Upstage Surrey presents - The Good Guard 18th September 2026</u></b><br/>A play for radio -  The Good Guard -Define Good. Starring Ray James. Written by Carole Thorpe.<br/>Click to listen:  <u><a href="https://example.com/UpstageSurrey-TheGoodGuard2026-09-18.mp3" target="_blank">UpstageSurrey-TheGoodGuard2026-09-18.mp3</a></u><br/><br/><b><u>Upstage Surrey presents - The Kiss of Death 19th June 2026</u></b><br/>A play for radio -  The Kiss of Death - Written by A. Writer.<br/>Click to listen:  <u><a href="https://example.com/kiss-of-death.mp3">kiss-of-death.mp3</a></u><br/><br/><b><u>Upstage Surrey presents - The Kiss 19th June 2026</u></b><br/>A play for radio -  The Kiss - O, how ripe in show Thy lips.<br/>Click to listen:  <u><a href="https://example.com/the-kiss.mp3">the-kiss.mp3</a></u><br/><br/>
</ol>
"""


class ParseBrooklandsPlayTests(TestCase):
    def test_finds_the_text_and_url(self):
        text, url = parse_brooklands_play(SAMPLE_LIST, "The Good Guard")
        self.assertEqual(text, "The Good Guard -Define Good. Starring Ray James. Written by Carole Thorpe.")
        self.assertEqual(url, "https://example.com/UpstageSurrey-TheGoodGuard2026-09-18.mp3")

    def test_title_is_matched_ignoring_case(self):
        self.assertEqual(parse_brooklands_play(SAMPLE_LIST, "the good guard")[1].rsplit("/", 1)[1],
                         "UpstageSurrey-TheGoodGuard2026-09-18.mp3")

    def test_a_longer_title_does_not_match_a_shorter_name(self):
        # "The Kiss" is the play after "The Kiss of Death": it must not take the first entry.
        text, url = parse_brooklands_play(SAMPLE_LIST, "The Kiss")
        self.assertEqual(url, "https://example.com/the-kiss.mp3")
        self.assertTrue(text.startswith("The Kiss - O, how ripe"))

    def test_unknown_play_returns_none(self):
        self.assertIsNone(parse_brooklands_play(SAMPLE_LIST, "No Such Play"))


class FindBrooklandsPlayLiveTests(TestCase):
    """Visits the real Brooklands Radio Playhouse page, so needs the internet."""

    def test_the_good_guard(self):
        result = find_brooklands_play("The Good Guard")
        print("\nThe Good Guard:", result)
        self.assertIsNotNone(result, "The Good Guard is not listed on the Playhouse page")
        text, url = result
        self.assertIn("Written by", text)
        self.assertTrue(url.startswith("http") and url.endswith(".mp3"), url)


class ParseBrooklandsBlurbTests(TestCase):
    """The blurb is what follows the "-" after the play's name, up to a cast list, writer or director."""

    def blurb(self, title, text):
        return parse_brooklands_blurb(text, title)

    def test_stops_at_a_cast_list(self):
        self.assertEqual(self.blurb("The Good Guard", "The Good Guard -Define Good. Starring Ray James as Dimitri Ivanov."),
                         "Define Good.")

    def test_stops_at_the_writer(self):
        self.assertEqual(
            self.blurb("The Kiss", "The Kiss - O, how ripe in show Thy lips kissing cherries tempting grow. Written  by Peter Bridge"),
            "O, how ripe in show Thy lips kissing cherries tempting grow.",
        )

    def test_stops_at_writer_and_director(self):
        self.assertEqual(
            self.blurb("Giants of Science", "Giants of Science - Revelations in A&E after the pubs close. Written and directed by Pip Rolls"),
            "Revelations in A&E after the pubs close.",
        )

    def test_a_credit_lead_in_is_left_out(self):
        self.assertEqual(
            self.blurb("A Pyrrhic Victory", "A Pyrrhic Victory - Rose and Connie are friends. A one-hour radio play written and directed by Emma"),
            "Rose and Connie are friends.",
        )

    def test_stops_at_a_cast_list_with_no_marker(self):
        self.assertEqual(
            self.blurb("Breakout", "Breakout - Idle chatter on a park bench. Darren Partridge as Sam, Tarryn Meaker as Emma."),
            "Idle chatter on a park bench.",
        )

    def test_the_title_need_not_start_the_text(self):
        self.assertEqual(
            self.blurb("Snippets the Sequel", "Presents Snippets the Sequel - There may be trouble ahead. Written and directed by Celia"),
            "There may be trouble ahead.",
        )

    def test_empty_when_the_credits_follow_the_dash_straight_away(self):
        self.assertEqual(self.blurb("Bodyguard", "Bodyguard - A play for radio written by Peter Drake"), "")
        self.assertEqual(self.blurb("Coffee", "Coffee - Written by Peter Bridge"), "")

    def test_empty_when_there_is_no_dash_after_the_name(self):
        self.assertEqual(self.blurb("Lost In The Madhouse", "Lost In The Madhouse written by Peter Shaw. Mike Strong as Lennie"), "")
        self.assertEqual(self.blurb("Evolution", "Evolution: What Really happened? Written and directed by Pip Rolls."), "")

    def test_empty_when_the_name_is_not_in_the_text(self):
        self.assertEqual(self.blurb("AI", "A grieving robotics genius is faced with a crisis. Written by Darren"), "")
        self.assertEqual(self.blurb("The Good Guard", ""), "")

    def test_a_mangled_apostrophe_still_matches_the_title(self):
        self.assertEqual(self.blurb("Alfred's Tale", "Alfred�s Tale - Cake. Written by Pip"), "Cake.")

    def test_plays_in_a_list(self):
        plays = brooklands_plays(SAMPLE_LIST)
        self.assertEqual([play["title"] for play in plays], ["The Good Guard", "The Kiss of Death", "The Kiss"])
        self.assertEqual(plays[0]["date"], "18th September 2026")
        self.assertEqual(plays[0]["text"], "Define Good.")
        self.assertEqual(plays[2]["listen_url"], "https://example.com/the-kiss.mp3")


class BrooklandsPlaysLiveTests(TestCase):
    """Reads the whole real Playhouse list, so needs the internet."""

    def test_print_all_plays(self):
        print()
        print_brooklands_plays()
        plays = brooklands_plays()
        self.assertGreater(len(plays), 20)
        self.assertTrue(all(play["listen_url"] for play in plays))
        good_guard = next(play for play in plays if play["title"] == "The Good Guard")
        self.assertEqual(good_guard["text"], "Define Good.")


class SplitTitleDateTests(TestCase):
    """A heading's title ends at its date (a number) or at "Part"."""

    def test_title_ends_at_the_date(self):
        self.assertEqual(_split_title_date("The Good Guard 18th September 2026"), ("The Good Guard", "18th September 2026", ""))

    def test_date_with_no_space_before_it(self):
        self.assertEqual(_split_title_date("The Absence of Peas17th January 2025")[:2], ("The Absence of Peas", "17th January 2025"))

    def test_title_ends_at_part(self):
        self.assertEqual(_split_title_date("Cinderella Part 2 3rd January 2026"), ("Cinderella", "3rd January 2026", "Part 2"))
        self.assertEqual(_split_title_date("Cinderella Part Two 3rd January 2026"), ("Cinderella", "3rd January 2026", "Part Two"))
        self.assertEqual(_split_title_date("Cinderella part 2"), ("Cinderella", "", "part 2"))

    def test_words_that_only_look_like_part_stay_in_the_title(self):
        for title in ("A Part Time Lover", "Part of the Furniture", "Party Games"):
            self.assertEqual(_split_title_date(f"{title} 2nd May 2020")[0], title)

    def test_part_may_sit_between_the_name_and_the_dash_in_the_text(self):
        self.assertEqual(parse_brooklands_blurb("Cinderella Part 2 - A panto sequel. Starring Ann as Cinders", "Cinderella"),
                         "A panto sequel.")


class HeadingPrefixTests(TestCase):
    """"Upstage Surrey presents" is not always followed by a dash, and "presents" sometimes has a capital."""

    def entry(self, heading):
        return (
            f"<b><u>{heading}</u></b><br/>A play for radio -  Some Play - A blurb. Written by A. Writer.<br/>"
            '<br/>Click to listen:  <u><a href="https://example.com/play.mp3">play.mp3</a></u><br/><br/>'
        )

    def test_headings_with_and_without_the_dash(self):
        for heading in (
            "Upstage Surrey presents - Jack and The Beanstalk 20th December 2024",
            "Upstage Surrey presents Jack and The Beanstalk 20th December 2024",
            "Upstage Surrey presents-Jack and The Beanstalk 20th December 2024",
            "Upstage Surrey Presents - Jack and The Beanstalk 20th December 2024",
            "upstage surrey presents – Jack and The Beanstalk 20th December 2024",
        ):
            plays = brooklands_plays(self.entry(heading))
            self.assertEqual([(play["title"], play["date"]) for play in plays],
                             [("Jack and The Beanstalk", "20th December 2024")], heading)
            self.assertEqual(plays[0]["listen_url"], "https://example.com/play.mp3")

    def test_a_dash_between_the_title_and_the_date_is_not_part_of_the_title(self):
        plays = brooklands_plays(self.entry("Upstage Surrey presents The Frog Prince - 13th December 2024"))
        self.assertEqual((plays[0]["title"], plays[0]["date"]), ("The Frog Prince", "13th December 2024"))

    def test_other_bold_text_is_not_a_play(self):
        self.assertEqual(brooklands_plays("<b>Some other heading</b><br/>text"), [])

    def test_a_dash_before_part_is_not_part_of_the_title(self):
        self.assertEqual(_split_title_date("Welcome Home Mrs. Claus – Part 2 25th December 2025"),
                         ("Welcome Home Mrs. Claus", "25th December 2025", "Part 2"))

    def test_find_a_play_whose_heading_has_no_dash(self):
        html = self.entry("Upstage Surrey presents Jack and The Beanstalk 20th December 2024")
        self.assertEqual(parse_brooklands_play(html, "Jack and the Beanstalk")[1], "https://example.com/play.mp3")


class OtherHeadingStyleTests(TestCase):
    """Headings start "Upstage Surrey presents" or "Upstage Theatre Company -"; plays that start any other way are ignored."""

    def entry(self, heading, link=True):
        listen = '<br/>Click to listen:  <u><a href="https://example.com/play.mp3">play.mp3</a></u>' if link else ""
        return f"<b><u>{heading}</u></b><br/>{heading.split(' - ')[-1].split(' 3')[0]} - A blurb. Written by A. Writer.{listen}<br/><br/>"

    def test_upstage_theatre_company_prefix(self):
        plays = brooklands_plays(self.entry("Upstage Theatre Company - Game Over 24th February 2021"))
        self.assertEqual([(play["title"], play["date"]) for play in plays], [("Game Over", "24th February 2021")])

    def test_plays_that_do_not_start_upstage_are_ignored(self):
        for heading in (
            "Speed Dating 30th March 2022",
            "Welcome Home Mrs. Claus \u2013 Part 2 25th December 2025",
            "Another Company presents - Speed Dating 30th March 2022",
        ):
            self.assertEqual(brooklands_plays(self.entry(heading)), [], heading)

    def test_part_in_an_upstage_heading(self):
        plays = brooklands_plays(self.entry("Upstage Surrey presents Welcome Home Mrs. Claus \u2013 Part 2 25th December 2025"))
        self.assertEqual((plays[0]["title"], plays[0]["part"]), ("Welcome Home Mrs. Claus", "Part 2"))

    def test_a_play_with_a_prefixed_heading_is_listed_even_without_a_link(self):
        plays = brooklands_plays(self.entry("Upstage Surrey presents - Speed Dating 30th March 2022", link=False))
        self.assertEqual((len(plays), plays[0]["listen_url"]), (1, None))


class CastWordingTests(TestCase):
    """The blurb stops before a cast list however it is worded."""

    def blurb(self, title, text):
        return parse_brooklands_blurb(text, title)

    def test_name_played_by_name(self):
        self.assertEqual(
            self.blurb("Jumpers", "Jumpers - The London rooftop is deserted. Rita played by Mills Ross, Paul played by Dave Andrew, Written by A."),
            "The London rooftop is deserted.",
        )

    def test_name_played_character_with_no_by(self):
        self.assertEqual(
            self.blurb("The Laundrette Final Spin", "The Laundrette Final Spin - It will all come out in the wash. Sarah Sommerville played Brenda, Sara Robinson played Maureen, Directed by K."),
            "It will all come out in the wash.",
        )

    def test_character_dash_played_by(self):
        self.assertEqual(
            self.blurb("Waiting For Shirley", "Waiting For Shirley - The best things come to those who wait. Man - played by Dave Andrew, Woman - played by Sara Robinson"),
            "The best things come to those who wait.",
        )

    def test_the_role_of_is_left_out(self):
        self.assertEqual(
            self.blurb("Meet Me At The Bridge", "Meet Me At The Bridge - The price of fame is too high. The role of Eddie played by Mills Ross, Written by A."),
            "The price of fame is too high.",
        )

    def test_cast_members_label(self):
        self.assertEqual(
            self.blurb("Speed Dating", "Speed Dating - Dates, fast. Cast members: Poppy Robinson, Christian Toms"),
            "Dates, fast.",
        )


class ParseBrooklandsCastTests(TestCase):
    def cast(self, text, known=()):
        return [(entry["character"], entry["actors"]) for entry in parse_brooklands_cast(text, known)]

    def test_starring_actor_as_character(self):
        self.assertEqual(
            self.cast("The Good Guard -Define Good. Starring Ray James as Dimitri Ivanov. Written by Carole Thorpe."),
            [("Dimitri Ivanov", ["Ray James"])],
        )

    def test_cast_with_no_marker_and_credits_after(self):
        self.assertEqual(
            self.cast("Last Super. Written by Mary Dawson. Sahera Chohan as Debbie, Emma White as Cindy. Directed by Karen Buchanan."),
            [("Debbie", ["Sahera Chohan"]), ("Cindy", ["Emma White"])],
        )

    def test_character_played_by_actor(self):
        self.assertEqual(
            self.cast("Jumpers - Blurb. Rita played by Mills Ross, Paul played by Dave Andrew, Written by A. Writer."),
            [("Rita", ["Mills Ross"]), ("Paul", ["Dave Andrew"])],
        )

    def test_character_dash_played_by_actor(self):
        self.assertEqual(
            self.cast("Waiting For Shirley - Blurb. Man - played by Dave Andrew, Radio host played by Albert Clogston, Directed by K."),
            [("Man", ["Dave Andrew"]), ("Radio host", ["Albert Clogston"])],
        )

    def test_actor_played_character(self):
        self.assertEqual(
            self.cast("Take 2 - Blurb. Sara Robinson played Maureen and Neil Armstrong played Larry, Editing by D."),
            [("Maureen", ["Sara Robinson"]), ("Larry", ["Neil Armstrong"])],
        )

    def test_the_role_of(self):
        self.assertEqual(
            self.cast("Bridge - Blurb. The role of Eddie played by Mills Ross, The role of Amanda played by Karen Buchanan, Written by A."),
            [("Eddie", ["Mills Ross"]), ("Amanda", ["Karen Buchanan"])],
        )

    def test_the_site_cuts_the_text_off_so_the_last_item_is_dropped(self):
        # "Martin Frost as Newton" might have been "Newton..." and "Nigella" is the start of a name.
        self.assertEqual(
            self.cast("Starring Sarah Edgar as Nurse, Lindsey Cruchett as Doctor, Martin Frost as Newton"),
            [("Nurse", ["Sarah Edgar"]), ("Doctor", ["Lindsey Cruchett"])],
        )
        # "Nigella" is the start of a name: it is dropped, and the two complete entries stay.
        self.assertEqual(self.cast("Starring Mark Cartwright as King Alfred, Lindsey Crutchett as the Old Crone, Nigella"),
                         [("King Alfred", ["Mark Cartwright"]), ("the Old Crone", ["Lindsey Crutchett"])])

    def test_a_single_cut_off_item_gives_no_cast(self):
        self.assertEqual(self.cast("Starring: Tess Towns"), [])

    def test_no_cast_in_the_text(self):
        self.assertEqual(self.cast("Contact! - Was there anybody there? Written and narrated by Lisa Mills."), [])
        self.assertEqual(self.cast(""), [])

    def test_junk_is_skipped(self):
        # A name run into a character ("Typhinia Mulford and Sylvia") is skipped, not made into a person.
        self.assertEqual(
            self.cast("Blurb. Matthew Baylis as David, Denise Rocard as DCI Hepper, Typhinia Mulford and Sylvia and Jonathan Howell as Vernon. Directed by Rax."),
            [("David", ["Matthew Baylis"]), ("Vernon", ["Jonathan Howell"])],
        )
        self.assertEqual(
            self.cast("Blurb. Rebecca Douglas as Elf and Police People are Marie- Jose Zuurbier, Wendy Megeney. Directed by X."), []
        )


class ParseBrooklandsCreditsTests(TestCase):
    def credits(self, text, title=""):
        return [(credit["role"], credit["name"]) for credit in parse_brooklands_credits(text, title)]

    def test_writer_director_and_editor(self):
        self.assertEqual(
            self.credits("Starring Ray James as Dimitri. Written by Carole Thorpe, Directed by Gary Langford and Edited by Nigel Greenaway."),
            [("Writer", "Carole Thorpe"), ("Director", "Gary Langford"), ("Editor", "Nigel Greenaway")],
        )

    def test_written_and_directed_by_gives_both_roles(self):
        self.assertEqual(self.credits("Written and directed by Pip Rolls and starring Sarah Edgar as Nurse"),
                         [("Writer", "Pip Rolls"), ("Director", "Pip Rolls")])

    def test_written_directed_and_edited_by(self):
        self.assertEqual(self.credits("Written, directed and edited by Darren R Partridge. Starring Matthew Bayliss as Dr. Mike"),
                         [("Writer", "Darren Partridge"), ("Director", "Darren Partridge"), ("Editor", "Darren Partridge")])

    def test_several_names_in_one_credit(self):
        self.assertEqual(self.credits("Written by Ann Smith and Bob Jones. Cast: Cy Dee as Eve."),
                         [("Writer", "Ann Smith"), ("Writer", "Bob Jones")])

    def test_variants_and_typos(self):
        self.assertEqual(self.credits("Witten by Mary Dawson, irected by Sara Robinson, edits by Colin Hansford."),
                         [("Writer", "Mary Dawson"), ("Director", "Sara Robinson"), ("Editor", "Colin Hansford")])

    def test_by_on_its_own_is_the_writer(self):
        self.assertEqual(self.credits("A panto for radio by Edgar Stephenson starring: Tryphena Mulford as Cinderella"),
                         [("Writer", "Sarah Edgar"), ("Writer", "Helen Stephenson")])  # the writing duo, by surnames
        self.assertEqual(self.credits("Looking for love at Christmas. By Clive Foskett with Tryphena Mulford as Suzanne"),
                         [("Writer", "Clive Foskett")])
        self.assertEqual(self.credits("High Infidelity by Peter Bridge. Matthew Baylis as David. Directed by Rax Lakhani."),
                         [("Writer", "Peter Bridge"), ("Director", "Rax Lakhani")])

    def test_directed_and_produced_by(self):
        self.assertEqual(self.credits("Written by Neil Armstrong and Directed and Produced by Tess Townsend. Starring A B as C."),
                         [("Writer", "Neil Armstrong"), ("Director", "Tess Townsend")])

    def test_names_stop_before_a_cast_list(self):
        self.assertEqual(self.credits("Written by Evon Wheeler, Caroline Tattersall as Daisy, Mandy Dowdney as Rebecca."),
                         [("Writer", "Evon Wheeler")])

    def test_the_last_name_is_dropped_when_the_text_is_cut_off(self):
        self.assertEqual(self.credits("Matthew Baylis as David. Witten by Richard Newbold, irected by Lis"),
                         [("Writer", "Richard Newbold")])
        self.assertEqual(self.credits("Streuth! Mark Bradford as Roger, Written by Graham La"), [])

    def test_read_by_narrated_by_and_upstage_are_not_credits(self):
        self.assertEqual(self.credits("Intoxicating Love - Read by Emma White, written and directed by Mary Dawson."),
                         [("Writer", "Mary Dawson"), ("Director", "Mary Dawson")])
        self.assertEqual(self.credits("Produced by Upstage Surrey. Narrated by Stephen Alexander."), [])
        self.assertEqual(self.credits("A play for radio by By Upstage and AI assistance, Directed by Karen Buchanan."),
                         [("Director", "Karen Buchanan")])
        self.assertEqual(self.credits("A play for radio by Upstage Surrey by Peter Bridge, Directed by Karen Buchanan."),
                         [("Writer", "Peter Bridge"), ("Director", "Karen Buchanan")])

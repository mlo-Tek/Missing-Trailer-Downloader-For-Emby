import unittest

from mtde.hardening import candidate_safety_reason


class SafetyRefinement0314Tests(unittest.TestCase):
    def test_legitimate_historical_trailers_are_not_auto_repaired(self):
        cases = [
            ("Alles steht Kopf 2", 2024, "Alles steht Kopf 2 I Offizieller Trailer"),
            ("Asterix in Amerika", 1994, "ASTERIX IN AMERIKA RESTAURIERUNG| Trailer Deutsch | Neu als Blu-ray, DVD und Digital!"),
            ("Asterix und Kleopatra", 1968, "Asterix und Kleopatra Bluray Trailer"),
            ("Cars 3 - Evolution", 2017, "CARS 3: Evolution Exklusiv Clip & Trailer German Deutsch (2017)"),
            ("Emoji - Der Film", 2017, "EMOJI: Der Film Exklusiv Trailer German Deutsch (2017)"),
            ("Findet Dorie", 2016, "FINDET DORIE Exklusiv Trailer 2 German Deutsch (2016)"),
            ("Freaky Friday - Ein voll verrückter Freitag", 2003, "Freaky Friday | Ein voll verrückter Freitag | GermanTrailer"),
            ("Hoppers", 2026, "Hoppers I Offizieller Trailer I Ab 5. März im Kino"),
            ("Hotel Transsilvanien", 2012, "HOTEL TRANSSILVANIEN 3D- HD Trailer deutsch | Ab 26.10.2012 im Kino"),
            ("Kevin - Allein in New York", 1992, "Kevin - Allein in New York (Deutscher Kinotrailer)"),
            ("Lilo & Stitch", 2002, "Lilo & Stitch I Trailer I Jetzt im Kino"),
            ("Mädchen Mädchen 2", 2004, "Mädchen, Mädchen 2 – Loft oder Liebe | 2004 | Kino Trailer | Deutsch | 4K"),
            ("Die Monster Uni", 2013, "DIE MONSTER UNI Extended Trailer 2 German Deutsch HD 2013"),
            ("Nightmare Before Christmas", 1993, "Nightmare before Christmas 3D Trailer deutsch"),
            ("Schneewittchen", 2025, "SCHNEEWITTCHEN Neuer Trailer German Deutsch (2025) Gal Gadot"),
            ("Sonic the Hedgehog", 2020, "Baby Sonic - SONIC: The Hedgehog Clip & Trailer German Deutsch (2020) Exklusiv"),
            ("Toy Story 5", 2026, "Lillypad verhöhnt Jessie! - TOY STORY 5 Clip & Trailer German Deutsch (2026)"),
            ("Wild Child", 2008, "Official Trailer | Wild Child | Screen Bites"),
            ("Zoomania 2", 2025, "ZOOMANIA 2 Neuer Trailer German Deutsch (2025)"),
        ]
        for movie, year, title in cases:
            with self.subTest(movie=movie, title=title):
                self.assertIsNone(candidate_safety_reason(title, movie, year))

    def test_known_bad_downloads_remain_repairable(self):
        cases = [
            ("Cars", 2006, "CARS ON THE ROAD Trailer German Deutsch (2022)"),
            ("Harry Potter und der Orden des Phönix", 2007, "Harry Potter und der Orden des Phönix-official trailer remake 2014 [German]"),
            ("Kung Fu Panda 3", 2016, "Kung Fu Panda 3 | Die deutschen Stimmen - Synchrontrailer | Deutsch HD DreamWorks"),
            ("Leroy & Stitch", 2006, "Leroy & Stitch (2006) - Hauptmenü (German/Deutsch) (DVD)"),
            ("Stitch & Co. - Der Film", 2003, "Stitch & Co. - Der Film (2003) - Hauptmenü (German/Deutsch) (DVD)"),
            ("Madagascar", 2005, "Madagascar - Trailer German/Deutsch (Reversed)"),
            ("Madagascar 2", 2008, "Madagascar: Escape 2 Africa (2008) We are unique in German"),
            ("Toy Story 3", 2010, "Barbie trifft Ken! - TOY STORY 3 Clip German Deutsch (2010)"),
            ("WALL·E - Der Letzte räumt die Erde auf", 2008, "Die Wohlstandsgesellschaft (WALL·E - Der Letzte räumt die Erde auf - 2008)"),
            ("Der König der Löwen 3 - Hakuna Matata", 2004, "Der König der Löwen 3 – Hakuna Matata (2004) Soundtrack: Gänge graben (längere Version)"),
            ("Stockmann", 2015, "Stockmann - Sinua varten, trailer"),
            ("Die Croods", 2013, "Die Croods - Alles auf Anfang – Trailer deutsch/german HD"),
            ("Sing", 2016, "Sing - Die Show deines Lebens Trailer Deutsch"),
        ]
        for movie, year, title in cases:
            with self.subTest(movie=movie, title=title):
                self.assertIsNotNone(candidate_safety_reason(title, movie, year))


if __name__ == "__main__":
    unittest.main()

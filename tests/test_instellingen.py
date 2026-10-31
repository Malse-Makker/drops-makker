import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drops_makker import instellingen as inst  # noqa: E402

LEGE_OMGEVING = {k: "" for k in ("CHANNELS", "TWITCH_AUTH_TOKEN", "MATTERMOST_WEBHOOK", "DISCORD_WEBHOOK",
                                 "BROWSER", "POLL_SECONDS", "CLAIM_MINUTES", "RELOAD_HOURS")}


class KanaalUit(unittest.TestCase):
    def test_links_en_namen(self):
        for tekst in ("https://www.twitch.tv/WarThunder_Esports", "http://twitch.tv/warthunder_esports/",
                      "twitch.tv/warthunder_esports/videos?filter=all", "www.twitch.tv/warthunder_esports#x",
                      "https://m.twitch.tv/warthunder_esports", "  warthunder_esports ", "@WarThunder_Esports"):
            self.assertEqual(inst.kanaal_uit(tekst), "warthunder_esports", tekst)

    def test_ongeldig(self):
        for tekst in ("", "https://www.youtube.com/@warthunder", "naam met spaties", 'a"){x}', "x" * 26):
            with self.assertRaises(ValueError, msg=tekst):
                inst.kanaal_uit(tekst)


class Laden(unittest.TestCase):
    def setUp(self):
        self.map = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {**LEGE_OMGEVING, "DATA_DIR": str(self.map / "data")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def schrijf(self, tekst):
        pad = self.map / "instellingen.toml"
        pad.write_text(tekst, encoding="utf-8")
        return pad

    def test_zonder_bestand_het_voorbeeld(self):
        i = inst.laden(self.map / "bestaat-niet.toml")
        self.assertEqual(i.kanalen, ["warthunder_esports"])
        self.assertEqual(i.token, "")
        self.assertEqual(i.poll, 60)

    def test_voorbeeld_is_geldig(self):
        pad = self.map / "nieuw" / "instellingen.toml"
        self.assertTrue(inst.voorbeeld_schrijven(pad))
        self.assertFalse(inst.voorbeeld_schrijven(pad))
        self.assertEqual(inst.laden(pad).kanalen, ["warthunder_esports"])

    def test_volgorde_en_dubbelen(self):
        pad = self.schrijf('kanalen = ["https://www.twitch.tv/b", "a", "twitch.tv/B/"]\n'
                           '[meldingen]\ndiscord = "https://discord.example/hook"\n'
                           '[geavanceerd]\nclaim_minuten = 5\n')
        i = inst.laden(pad)
        self.assertEqual(i.kanalen, ["b", "a"])
        self.assertEqual(i.discord, "https://discord.example/hook")
        self.assertEqual(i.claim_minuten, 5)

    def test_omgeving_gaat_voor(self):
        pad = self.schrijf('kanalen = ["a"]\ntoken = "uitbestand"\n')
        with mock.patch.dict(os.environ, {"CHANNELS": "https://www.twitch.tv/x, y", "TWITCH_AUTH_TOKEN": "uitenv",
                                          "POLL_SECONDS": "30"}):
            i = inst.laden(pad)
        self.assertEqual(i.kanalen, ["x", "y"])
        self.assertEqual(i.token, "uitenv")
        self.assertEqual(i.poll, 30)

    def test_nieuwste_token_wint(self):
        pad = self.schrijf('kanalen = ["a"]\ntoken = "uitbestand"\n')
        oud = time.time() - 100
        os.utime(pad, (oud, oud))
        inst.token_opslaan(self.map / "data", "ingelogd", "iemand")
        self.assertEqual(inst.laden(pad).token, "ingelogd")
        # Daarna een nieuw token in het bestand geplakt: dat gaat dan voor.
        nieuw = time.time() + 100
        os.utime(pad, (nieuw, nieuw))
        self.assertEqual(inst.laden(pad).token, "uitbestand")

    def test_geen_kanalen(self):
        pad = self.schrijf("kanalen = []\n")
        with self.assertRaises(ValueError):
            inst.laden(pad)


if __name__ == "__main__":
    unittest.main()

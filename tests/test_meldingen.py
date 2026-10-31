import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drops_makker.meldingen import Melder, platte_tekst  # noqa: E402


def instellingen(**kw):
    basis = dict(mattermost="", discord="", windows_meldingen=True)
    return SimpleNamespace(**{**basis, **kw})


class Meldingen(unittest.TestCase):
    def verstuurd(self, inst, bureaublad=None):
        with mock.patch("urllib.request.urlopen") as urlopen:
            Melder(lambda: inst, bureaublad, op_achtergrond=False)("🎁 Drop opgehaald: **BT-7M**")
        return [(c.args[0].full_url, json.loads(c.args[0].data), dict(c.args[0].header_items()))
                for c in urlopen.call_args_list]

    def test_niets_ingesteld(self):
        self.assertEqual(self.verstuurd(instellingen()), [])

    def test_mattermost_en_discord(self):
        verzoeken = self.verstuurd(instellingen(mattermost="https://mm.example/hooks/a",
                                                discord="https://discord.example/api/webhooks/b"))
        self.assertEqual(verzoeken[0][0], "https://mm.example/hooks/a")
        self.assertEqual(verzoeken[0][1]["text"], "🎁 Drop opgehaald: **BT-7M**")
        self.assertEqual(verzoeken[1][1]["content"], "🎁 Drop opgehaald: **BT-7M**")
        self.assertIn("drops-makker", verzoeken[1][2]["User-agent"])

    def test_bureaublad_zonder_markdown(self):
        gezien = []
        self.verstuurd(instellingen(), gezien.append)
        self.assertEqual(gezien, ["🎁 Drop opgehaald: BT-7M"])
        gezien.clear()
        self.verstuurd(instellingen(windows_meldingen=False), gezien.append)
        self.assertEqual(gezien, [])

    def test_fout_bij_versturen_stopt_niets(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("weg")):
            Melder(lambda: instellingen(mattermost="https://mm.example/hooks/a"), op_achtergrond=False)("hoi")

    def test_platte_tekst(self):
        self.assertEqual(platte_tekst("**a** `b`"), "a b")


if __name__ == "__main__":
    unittest.main()

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drops_makker import bijwerken  # noqa: E402

INHOUD = b"MZ nieuwe exe"


def antwoord(data):
    r = io.BytesIO(data)
    return mock.MagicMock(__enter__=lambda s: r, __exit__=lambda *a: False, read=r.read)


class Versies(unittest.TestCase):
    def test_versie(self):
        self.assertEqual(bijwerken.versie("v1.10.2"), (1, 10, 2))
        self.assertEqual(bijwerken.versie("1.2"), (1, 2))
        self.assertEqual(bijwerken.versie("nachtelijk"), ())

    def test_nieuwer(self):
        with mock.patch.object(bijwerken, "__version__", "1.2.0"):
            self.assertTrue(bijwerken.nieuwer("1.10.0"))
            self.assertTrue(bijwerken.nieuwer("v1.2.1"))
            self.assertFalse(bijwerken.nieuwer("1.2.0"))
            self.assertFalse(bijwerken.nieuwer("1.1.9"))
            self.assertFalse(bijwerken.nieuwer("onzin"))

    def test_nieuwste(self):
        release = {"tag_name": "v1.3.0", "assets": [
            {"name": "drops-makker.exe", "browser_download_url": "https://x/exe"},
            {"name": "drops-makker.exe.sha256", "browser_download_url": "https://x/sha"}]}
        with mock.patch("urllib.request.urlopen", return_value=antwoord(json.dumps(release).encode())):
            self.assertEqual(bijwerken.nieuwste(), ("1.3.0", "https://x/exe", "https://x/sha"))


class Installeren(unittest.TestCase):
    def setUp(self):
        self.map = Path(tempfile.mkdtemp())
        self.exe = self.map / "drops-makker.exe"
        self.exe.write_bytes(b"MZ oude exe")

    def downloaden(self, controlesom):
        def urlopen(req, timeout=None):
            if req.full_url.endswith(".sha256"):
                return antwoord(f"{controlesom}  drops-makker.exe\n".encode())
            return antwoord(INHOUD)
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            return bijwerken.downloaden("https://x/drops-makker.exe", "https://x/drops-makker.exe.sha256", self.exe)

    def test_download_met_goede_controlesom(self):
        nieuw = self.downloaden(hashlib.sha256(INHOUD).hexdigest())
        self.assertEqual(nieuw, self.map / "drops-makker.exe.nieuw")
        self.assertEqual(nieuw.read_bytes(), INHOUD)

    def test_download_met_foute_controlesom(self):
        with self.assertRaises(RuntimeError):
            self.downloaden("0" * 64)
        self.assertEqual(sorted(p.name for p in self.map.iterdir()), ["drops-makker.exe"])

    def test_installeren_en_opruimen(self):
        nieuw = self.downloaden(hashlib.sha256(INHOUD).hexdigest())
        bijwerken.installeren(nieuw, exe=self.exe, starten=False)
        self.assertEqual(self.exe.read_bytes(), INHOUD)
        self.assertEqual((self.map / "drops-makker.exe.oud").read_bytes(), b"MZ oude exe")
        self.assertTrue(bijwerken.oud_opruimen(exe=self.exe))
        self.assertEqual(sorted(p.name for p in self.map.iterdir()), ["drops-makker.exe"])

    def test_mislukt_installeren_zet_de_oude_terug(self):
        with self.assertRaises(OSError):
            bijwerken.installeren(self.map / "bestaat-niet", exe=self.exe, starten=False)
        self.assertEqual(self.exe.read_bytes(), b"MZ oude exe")


if __name__ == "__main__":
    unittest.main()

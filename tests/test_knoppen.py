import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from drops_makker.kijker import CLAIMKNOP, WEIGERKNOP
except ImportError:  # zonder playwright geïnstalleerd
    CLAIMKNOP = WEIGERKNOP = None


@unittest.skipIf(CLAIMKNOP is None, "playwright niet geïnstalleerd")
class Knoppen(unittest.TestCase):
    def test_claimknop(self):
        for tekst in ("Claim Now", "Claim", "Nu claimen", "Claimen", "Jetzt einfordern", "Réclamer"):
            self.assertTrue(re.match(CLAIMKNOP, tekst, re.I), tekst)
        for tekst in ("Claimed", "Claim Now!", "Learn more"):
            self.assertFalse(re.match(CLAIMKNOP, tekst, re.I), tekst)

    def test_weigerknop(self):
        for tekst in ("Reject", "Reject All", "Weigeren", "Alles weigeren", "Ablehnen", "Refuser"):
            self.assertTrue(re.match(WEIGERKNOP, tekst, re.I), tekst)
        self.assertFalse(re.match(WEIGERKNOP, "Accept", re.I))


if __name__ == "__main__":
    unittest.main()

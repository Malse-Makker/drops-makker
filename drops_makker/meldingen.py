"""Meldingen naar Mattermost, Discord en het bureaublad."""
import json
import re
import threading
import urllib.request

from . import NAAM, __version__
from .logboek import log

USER_AGENT = f"{NAAM}/{__version__} (+https://github.com/Malse-Makker/drops-makker)"


def platte_tekst(tekst):
    """Zonder markdown, voor meldingen op het bureaublad."""
    return re.sub(r"\*\*|`", "", tekst)


def _posten(url, payload):
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            # Discord weigert verzoeken zonder eigen User-Agent.
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        urllib.request.urlopen(req, timeout=15).close()
    except Exception as e:
        log(f"melding versturen mislukt ({url.split('/')[2]}): {e}")


class Melder:
    """melden(tekst): logt en stuurt de tekst naar alle ingestelde kanalen.

    instellingen: functie die de actuele Instellingen geeft (die kunnen tussendoor
    wijzigen). bureaublad: functie die een melding op het scherm zet, of None.
    """

    def __init__(self, instellingen, bureaublad=None, op_achtergrond=True):
        self.instellingen = instellingen
        self.bureaublad = bureaublad
        self.op_achtergrond = op_achtergrond

    def _versturen(self, url, payload):
        if self.op_achtergrond:
            # Niet de kijker laten wachten op een trage webhook.
            threading.Thread(target=_posten, args=(url, payload), daemon=True).start()
        else:
            _posten(url, payload)

    def __call__(self, tekst):
        log(tekst)
        inst = self.instellingen()
        if inst.mattermost:
            self._versturen(inst.mattermost, {"text": tekst, "username": NAAM})
        if inst.discord:
            self._versturen(inst.discord, {"content": tekst[:2000], "username": NAAM})
        if self.bureaublad and inst.windows_meldingen:
            try:
                self.bureaublad(platte_tekst(tekst))
            except Exception as e:
                log(f"melding op het bureaublad mislukt: {e}")

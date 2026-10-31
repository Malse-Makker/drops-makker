"""Icoon in het systeemvak (Windows). De kijker draait in een eigen thread."""
import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

import pystray

from . import NAAM, __version__, bijwerken
from . import instellingen as inst_mod
from .icoon import icoon_maken
from .kijker import Kijker
from .logboek import log

RUN_SLEUTEL = r"Software\Microsoft\Windows\CurrentVersion\Run"


def openen(pad):
    if sys.platform == "win32":
        os.startfile(pad)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(pad)])


def _startcommando():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" -m drops_makker --tray'


def autostart_aan():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_SLEUTEL) as k:
            winreg.QueryValueEx(k, NAAM)
        return True
    except OSError:
        return False


def autostart_wisselen():
    import winreg
    aan = autostart_aan()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_SLEUTEL, 0, winreg.KEY_SET_VALUE) as k:
        if aan:
            winreg.DeleteValue(k, NAAM)
        else:
            winreg.SetValueEx(k, NAAM, 0, winreg.REG_SZ, _startcommando())


def main(config_pad=None, na_update=None):
    config_pad = Path(config_pad) if config_pad else inst_mod.standaard_config()
    eerste_keer = inst_mod.voorbeeld_schrijven(config_pad)

    icon = pystray.Icon(NAAM, icoon_maken(), NAAM)
    status = {"tekst": "Opstarten"}

    def status_bijwerken(tekst):
        status["tekst"] = tekst
        icon.title = f"{NAAM}: {tekst}"[:127]
        icon.update_menu()

    def bureaublad(tekst):
        icon.notify(tekst[:250], NAAM)

    kijker = Kijker(config_pad, bureaublad=bureaublad, status=status_bijwerken)
    kijker.updates_melden = False  # dat doet bijwerken() hieronder

    def draaien():
        try:
            asyncio.run(kijker.run())
        except Exception as e:
            log(f"de kijker is gestopt door een fout: {e}")
            status_bijwerken(f"Gestopt door een fout: {str(e)[:60]}")

    threads = {"kijker": threading.Thread(target=draaien, daemon=True)}
    gestopt = threading.Event()
    bezig = threading.Lock()
    gemeld = {"versie": None}

    def kijker_stoppen():
        kijker.vraag_stop()
        threads["kijker"].join(timeout=60)

    def afsluiten():
        gestopt.set()
        kijker_stoppen()
        icon.stop()

    def bijwerken_zoeken(handmatig=False):
        if not bezig.acquire(blocking=False):
            return
        try:
            _bijwerken_zoeken(handmatig)
        except Exception as e:
            log(f"bijwerken mislukt: {e}")
            bureaublad(f"Bijwerken lukte niet: {e}")
        finally:
            bezig.release()

    def _bijwerken_zoeken(handmatig):
        modus = kijker.inst.updates
        if modus == "uit" and not handmatig:
            return
        try:
            versie, exe_url, sha_url = bijwerken.nieuwste()
        except Exception as e:
            log(f"zoeken naar updates mislukt: {e}")
            if handmatig:
                bureaublad("Zoeken naar updates lukte niet. Probeer het later opnieuw.")
            return
        if not bijwerken.nieuwer(versie):
            if handmatig:
                bureaublad(f"Je hebt de nieuwste versie ({__version__}).")
            return
        zelf = bijwerken.kan_zichzelf_bijwerken() and exe_url and sha_url
        if not zelf or (modus != "auto" and not handmatig):
            if versie != gemeld["versie"]:
                gemeld["versie"] = versie
                bureaublad(f"Er is een nieuwe versie van drops-makker: {versie}. "
                           + ("Kies Zoeken naar updates om bij te werken." if zelf
                              else f"Download hem op {bijwerken.RELEASES_URL}"))
            return
        # Niet midden in een stream, tenzij je er zelf om vraagt.
        while not handmatig and kijker.staat == "kijken":
            if gestopt.wait(60):
                return
        try:
            nieuw = bijwerken.downloaden(exe_url, sha_url)
        except PermissionError:
            bureaublad(f"Bijwerken kan niet in deze map. Download versie {versie} zelf: {bijwerken.RELEASES_URL}")
            return
        log(f"bijwerken van {__version__} naar {versie}")
        kijker_stoppen()
        try:
            bijwerken.installeren(nieuw)
        except Exception:
            # Oude versie blijft: kijker weer aan.
            threads["kijker"] = threading.Thread(target=draaien, daemon=True)
            threads["kijker"].start()
            raise
        gestopt.set()
        icon.stop()

    def bijwerk_lus():
        # Even wachten na het opstarten: bij het aanzetten van de pc is het
        # netwerk er niet altijd meteen.
        if gestopt.wait(30):
            return
        while True:
            bijwerken_zoeken()
            if gestopt.wait(6 * 3600):
                return

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda item: status["tekst"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Inloggen bij Twitch…", kijker.vraag_inloggen),
        pystray.MenuItem("Browser tonen", kijker.wissel_venster, checked=lambda item: kijker.zichtbaar),
        pystray.MenuItem("Instellingen openen", lambda: openen(config_pad)),
        pystray.MenuItem("Logboek openen", lambda: openen(kijker.inst.log_pad)),
        pystray.MenuItem("Start met Windows", autostart_wisselen, checked=lambda item: autostart_aan(),
                         visible=sys.platform == "win32"),
        pystray.MenuItem(f"Zoeken naar updates (nu {__version__})",
                         lambda: threading.Thread(target=bijwerken_zoeken, args=(True,), daemon=True).start()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Afsluiten", afsluiten),
    )

    def klaar(icon):
        icon.visible = True
        # Eerste keer: meteen het inlogvenster openen.
        kijker.inloggen_bij_start = not kijker.inst.token
        threads["kijker"].start()
        threading.Thread(target=bijwerk_lus, daemon=True).start()
        if eerste_keer:
            bureaublad("drops-makker draait in het systeemvak. Log in bij Twitch in het venster dat opent; "
                       "kanalen pas je aan via Instellingen openen.")
        elif na_update:
            bureaublad(f"drops-makker is bijgewerkt van {na_update} naar {__version__}.")

    icon.run(setup=klaar)

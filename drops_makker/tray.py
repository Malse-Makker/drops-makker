"""Icoon in het systeemvak (Windows). De kijker draait in een eigen thread."""
import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

import pystray

from . import NAAM
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


def main(config_pad=None):
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

    def draaien():
        try:
            asyncio.run(kijker.run())
        except Exception as e:
            log(f"de kijker is gestopt door een fout: {e}")
            status_bijwerken(f"Gestopt door een fout: {str(e)[:60]}")

    thread = threading.Thread(target=draaien, daemon=True)

    def afsluiten():
        kijker.vraag_stop()
        thread.join(timeout=30)
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda item: status["tekst"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Inloggen bij Twitch…", kijker.vraag_inloggen),
        pystray.MenuItem("Browser tonen", kijker.wissel_venster, checked=lambda item: kijker.zichtbaar),
        pystray.MenuItem("Instellingen openen", lambda: openen(config_pad)),
        pystray.MenuItem("Logboek openen", lambda: openen(kijker.inst.log_pad)),
        pystray.MenuItem("Start met Windows", autostart_wisselen, checked=lambda item: autostart_aan(),
                         visible=sys.platform == "win32"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Afsluiten", afsluiten),
    )

    def klaar(icon):
        icon.visible = True
        thread.start()
        if not kijker.inst.token:
            # Eerste keer: meteen het inlogvenster openen.
            kijker.vraag_inloggen()
        if eerste_keer:
            bureaublad("drops-makker draait in het systeemvak. Log in bij Twitch in het venster dat opent; "
                       "kanalen pas je aan via Instellingen openen.")

    icon.run(setup=klaar)

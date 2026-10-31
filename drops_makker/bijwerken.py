"""Nieuwe versies zoeken op GitHub, en de Windows-app zichzelf laten bijwerken.

Een draaiende exe mag op Windows niet overschreven worden, maar wel hernoemd:
de oude wordt drops-makker.exe.oud, de nieuwe komt op zijn plek en start. De
nieuwe ruimt de .oud daarna op.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import NAAM, __version__
from .logboek import log

REPO = "Malse-Makker/drops-makker"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE = f"{NAAM}.exe"
USER_AGENT = f"{NAAM}/{__version__} (+https://github.com/{REPO})"


def versie(tekst):
    """'v1.2.3' -> (1, 2, 3); iets onleesbaars -> ()."""
    try:
        return tuple(int(d) for d in str(tekst).strip().lstrip("vV").split("."))
    except ValueError:
        return ()


def nieuwer(v):
    return versie(v) > versie(__version__)


def kan_zichzelf_bijwerken():
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _ophalen(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def nieuwste():
    """(versie, exe-url, sha256-url) van de nieuwste release. De urls zijn None als
    die bestanden er niet bij staan."""
    with _ophalen(API_URL) as r:
        release = json.load(r)
    bestanden = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    return release["tag_name"].lstrip("vV"), bestanden.get(EXE), bestanden.get(EXE + ".sha256")


def _naast_exe(achtervoegsel, exe=None):
    exe = Path(exe or sys.executable)
    return exe.with_name(exe.name + achtervoegsel)


def downloaden(exe_url, sha_url, exe=None):
    """Downloadt de nieuwe exe naast de huidige als .nieuw en controleert de
    controlesom. Geeft het pad."""
    with _ophalen(sha_url) as r:
        verwacht = r.read().decode().split()[0].lower()
    doel = _naast_exe(".nieuw", exe)
    tmp = _naast_exe(".download", exe)
    h = hashlib.sha256()
    with _ophalen(exe_url, timeout=60) as r, open(tmp, "wb") as f:
        while blok := r.read(1 << 20):
            f.write(blok)
            h.update(blok)
    if h.hexdigest() != verwacht:
        tmp.unlink()
        raise RuntimeError("de controlesom van de download klopt niet")
    tmp.replace(doel)
    return doel


def klaarzetten(bron, exe=None):
    """Een exe die al op de computer staat klaarzetten als .nieuw (voor --bijwerken-van)."""
    doel = _naast_exe(".nieuw", exe)
    shutil.copyfile(bron, doel)
    return doel


def installeren(nieuw, extra_args=(), exe=None, starten=True):
    """Zet de nieuwe exe op de plek van de huidige en start hem. De aanroeper
    sluit daarna zelf af."""
    huidig = Path(exe or sys.executable)
    oud = _naast_exe(".oud", huidig)
    if oud.exists():
        oud.unlink()
    huidig.rename(oud)
    try:
        Path(nieuw).rename(huidig)
    except OSError:
        oud.rename(huidig)
        raise
    if starten:
        env = dict(os.environ)
        # Anders denkt de nieuwe exe dat hij een deel van deze PyInstaller-app is.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        vlaggen = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(huidig), "--na-update", __version__, *extra_args], env=env, close_fds=True,
                         creationflags=vlaggen)
    log(f"nieuwe versie geïnstalleerd in {huidig}")


def oud_opruimen(wachten=0, exe=None):
    """Haalt de .oud van een vorige update weg. Die zit vast tot het oude proces weg is."""
    oud = _naast_exe(".oud", exe)
    for f in (_naast_exe(".download", exe), _naast_exe(".nieuw", exe)):
        try:
            f.unlink()
        except OSError:
            pass
    einde = time.monotonic() + wachten
    while oud.exists():
        try:
            oud.unlink()
        except OSError:
            if time.monotonic() >= einde:
                log(f"{oud.name} opruimen lukt nog niet")
                return False
            time.sleep(1)
    return True

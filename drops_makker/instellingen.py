"""Instellingen uit instellingen.toml, met omgevingsvariabelen (Docker) erbovenop."""
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import NAAM

VOORBEELD = """\
# Instellingen van drops-makker.
# Wijzigingen worden binnen een minuut vanzelf opgepakt.

# Twitch-kanalen: een link of alleen de naam. drops-makker kijkt altijd naar
# het bovenste kanaal dat live is. Gaat een hoger kanaal live, dan stapt hij
# daarnaar over.
kanalen = [
    "https://www.twitch.tv/warthunder_esports",
]

# Inloggen gaat het makkelijkst via "Inloggen bij Twitch" in het menu
# (Windows) of met `drops-makker --inloggen`. Zonder scherm (server, Pi
# zonder bureaublad) plak je hier de waarde van het cookie auth-token van
# twitch.tv (zie de README).
token = ""

[meldingen]
# Webhook-adressen voor meldingen (live, drop opgehaald, token verlopen).
# Leeg laten = uit.
mattermost = ""
discord = ""
# Meldingen rechtsonder in Windows.
windows = true

[geavanceerd]
# auto, chrome, msedge, chromium, of het pad naar de browser tussen enkele
# aanhalingstekens, bijvoorbeeld 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'.
browser = "auto"
# Kijken zonder browservenster, zodat er niets de focus van je spel kan pakken.
# Op false (of via Browser tonen in het menu) zie je de browser wel.
browser_verbergen = true
poll_seconden = 60
claim_minuten = 15
herlaad_uren = 3
# Updates: "auto" (de Windows-app werkt zichzelf bij als er geen stream loopt,
# anders alleen een melding), "melden" (alleen een melding) of "uit".
updates = "auto"
"""

_KANAAL = re.compile(r"[a-z0-9_]{1,25}")


def kanaal_uit(tekst: str) -> str:
    """Kanaalnaam uit een Twitch-link of naam: 'https://www.twitch.tv/Naam/videos' -> 'naam'."""
    t = tekst.strip().lower()
    t = re.sub(r"^(https?://)?((www|m)\.)?twitch\.tv/", "", t)
    t = re.split(r"[/?#]", t, maxsplit=1)[0].lstrip("@")
    if not _KANAAL.fullmatch(t):
        raise ValueError(f"geen geldig Twitch-kanaal: {tekst!r}")
    return t


def config_map() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / NAAM
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NAAM
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / NAAM


def data_map() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NAAM
    if sys.platform == "darwin":
        return config_map()
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / NAAM


def standaard_config() -> Path:
    return config_map() / "instellingen.toml"


@dataclass
class Instellingen:
    kanalen: list[str]
    token: str = ""
    mattermost: str = ""
    discord: str = ""
    windows_meldingen: bool = True
    browser: str = "auto"
    browser_verbergen: bool = True
    poll: int = 60
    claim_minuten: int = 15
    herlaad_uren: int = 3
    updates: str = "auto"
    data: Path = field(default_factory=data_map)
    config_pad: Path | None = None

    @property
    def profiel(self) -> Path:
        return self.data / "profiel"

    @property
    def status_pad(self) -> Path:
        return self.data / "status.json"

    @property
    def account_pad(self) -> Path:
        return self.data / "account.json"

    @property
    def log_pad(self) -> Path:
        return self.data / f"{NAAM}.log"


def voorbeeld_schrijven(pad: Path) -> bool:
    """Schrijft het voorbeeldbestand als er nog geen instellingen zijn."""
    if pad.exists():
        return False
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(VOORBEELD, encoding="utf-8")
    return True


def token_opslaan(data: Path, token: str, login: str):
    data.mkdir(parents=True, exist_ok=True)
    pad = data / "account.json"
    pad.write_text(json.dumps({"token": token, "login": login}), encoding="utf-8")
    if os.name == "posix":
        pad.chmod(0o600)


def _opgeslagen_token(data: Path) -> tuple[str, float]:
    pad = data / "account.json"
    try:
        return json.loads(pad.read_text(encoding="utf-8")).get("token", ""), pad.stat().st_mtime
    except (OSError, ValueError):
        return "", 0.0


def _updates(waarde):
    waarde = str(waarde).strip().lower()
    if waarde not in ("auto", "melden", "uit"):
        raise ValueError(f"updates moet auto, melden of uit zijn, niet {waarde!r}")
    return waarde


def laden(config_pad: Path | None = None) -> Instellingen:
    pad = Path(config_pad) if config_pad else standaard_config()
    if pad.exists():
        with open(pad, "rb") as f:
            ruw = tomllib.load(f)
        config_tijd = pad.stat().st_mtime
    else:
        ruw, config_tijd = tomllib.loads(VOORBEELD), 0.0
    meld = ruw.get("meldingen", {})
    gev = ruw.get("geavanceerd", {})
    env = os.environ.get

    kanalen = []
    bron = env("CHANNELS").split(",") if env("CHANNELS") else ruw.get("kanalen", [])
    for k in bron:
        if k.strip() and (naam := kanaal_uit(k)) not in kanalen:
            kanalen.append(naam)
    if not kanalen:
        raise ValueError(f"geen kanalen ingesteld (in {pad} of CHANNELS)")

    data = data_map()
    # Het token uit de omgeving gaat voor. Anders het nieuwste van de twee:
    # plakken in het bestand of inloggen via het menu.
    token = env("TWITCH_AUTH_TOKEN", "").strip()
    if not token:
        opgeslagen, opgeslagen_tijd = _opgeslagen_token(data)
        uit_config = str(ruw.get("token", "")).strip()
        token = opgeslagen if opgeslagen and (opgeslagen_tijd >= config_tijd or not uit_config) else uit_config

    return Instellingen(
        kanalen=kanalen,
        token=token,
        mattermost=env("MATTERMOST_WEBHOOK") or meld.get("mattermost", ""),
        discord=env("DISCORD_WEBHOOK") or meld.get("discord", ""),
        windows_meldingen=bool(meld.get("windows", True)),
        browser=env("BROWSER") or gev.get("browser", "auto"),
        browser_verbergen=bool(gev.get("browser_verbergen", True)),
        poll=int(env("POLL_SECONDS") or gev.get("poll_seconden", 60)),
        claim_minuten=int(env("CLAIM_MINUTES") or gev.get("claim_minuten", 15)),
        herlaad_uren=int(env("RELOAD_HOURS") or gev.get("herlaad_uren", 3)),
        updates=_updates(env("UPDATES") or gev.get("updates", "auto")),
        data=data,
        config_pad=pad,
    )

"""De kijker: wacht tot een kanaal live is en kijkt dan mee in een echte browser.

De speler staat aan met geluid, maar de browser zelf is gedempt (--mute-audio),
net als een gedempt tabblad: een gedempte speler telt niet mee voor drops.
"""
import asyncio
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path

from playwright.async_api import Error as PWError
from playwright.async_api import async_playwright

from . import NAAM, __version__, bijwerken, twitch
from . import instellingen as inst_mod
from .logboek import log
from .meldingen import Melder

INVENTARIS_URL = "https://www.twitch.tv/drops/inventory"
HOE_INLOGGEN = ("Log opnieuw in via het menu (Inloggen bij Twitch) of met `drops-makker --inloggen`, "
                "of zet een nieuw token in de instellingen of in TWITCH_AUTH_TOKEN.")

# Wordt bij elke paginalading opnieuw gezet, vóór de speler start: geluid aan
# op halve sterkte en de laagste kwaliteit (scheelt bandbreedte en cpu).
INIT_SCRIPT = """
try {
  localStorage.setItem('video-muted', JSON.stringify({default: false}));
  localStorage.setItem('volume', '0.5');
  localStorage.setItem('video-quality', JSON.stringify({default: '160p30'}));
} catch (e) {}
"""

CHROME_ARGS = [
    "--mute-audio",  # zelfde als het tabblad dempen; de speler zelf blijft aan
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--no-first-run",
    "--no-default-browser-check",
    "--lang=en-US",
    "--window-size=1280,800",
]

SPELER_JS = """() => {
  const v = document.querySelector('[data-a-target="video-player"] video') || document.querySelector('video');
  if (!v) return null;
  return {paused: v.paused, muted: v.muted, volume: Math.round(v.volume * 100) / 100,
          time: Math.round(v.currentTime), height: v.videoHeight, ready: v.readyState};
}"""

# Naam van de drop bij een claimknop: de tekst van het eerste omliggende blok
# dat meer bevat dan de knop zelf.
DROPNAAM_JS = """b => {
  const eigen = b.innerText.trim();
  let e = b;
  for (let i = 0; i < 6 && e.parentElement; i++) {
    e = e.parentElement;
    const t = e.innerText.replace(eigen, '').trim();
    if (t.length > 3) return t.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 2).join(' - ').slice(0, 120);
  }
  return '?';
}"""

# Voortgang in de inventaris staat als "60% of 10 hours" onder de naam van de drop.
VOORTGANG_JS = """() => {
  const regels = (document.querySelector('main') || document.body).innerText
    .split('\\n').map(s => s.trim()).filter(Boolean);
  const uit = [];
  regels.forEach((r, i) => {
    if (/^\\d+\\s?%\\s+of\\b/i.test(r) && uit.length < 12) uit.push((i > 0 ? regels[i - 1] + ': ' : '') + r);
  });
  return uit;
}"""

CLAIMKNOP = r"^\s*claim( now)?\s*$"

# Eerste pagina van het inlogvenster: maakt duidelijk dat dit niet je eigen
# Chrome of Edge is.
WELKOM_HTML = """<!doctype html>
<meta charset="utf-8">
<title>drops-makker: inloggen bij Twitch</title>
<style>
  body { font-family: system-ui, sans-serif; background: #18181b; color: #efeff1; margin: 0;
         min-height: 100vh; display: grid; place-items: center; }
  main { max-width: 32rem; padding: 2rem; text-align: center; line-height: 1.5; }
  h1 { color: #bf94ff; }
  a { display: inline-block; margin-top: 1rem; padding: .8rem 1.6rem; background: #9146ff; color: #fff;
      border-radius: .4rem; text-decoration: none; font-weight: 600; }
</style>
<main>
  <h1>drops-makker</h1>
  <p>Dit is het browservenster van drops-makker, los van je eigen browser.
     Je bladwijzers en opgeslagen wachtwoorden zitten hier niet in.</p>
  <p>Log in bij Twitch met het account waarmee je drops wilt verzamelen.
     Zodra je bent ingelogd, sluit dit venster vanzelf.</p>
  <a href="https://www.twitch.tv/login">Inloggen bij Twitch</a>
</main>
"""


class NietIngelogd(Exception):
    pass


# --- browser zoeken en starten ---------------------------------------------

def _windows_paden(*delen):
    return [Path(os.environ[v], *delen) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
            if os.environ.get(v)]


def _kandidaten(soort):
    if sys.platform == "win32":
        return {
            "chrome": _windows_paden("Google", "Chrome", "Application", "chrome.exe"),
            "msedge": _windows_paden("Microsoft", "Edge", "Application", "msedge.exe"),
            "chromium": _windows_paden("Chromium", "Application", "chrome.exe"),
        }[soort]
    if sys.platform == "darwin":
        return [Path({
            "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "msedge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "chromium": "/Applications/Chromium.app/Contents/MacOS/Chromium",
        }[soort])]
    vast = {"chrome": ["/opt/google/chrome/chrome"], "msedge": ["/opt/microsoft/msedge/msedge"], "chromium": []}
    namen = {"chrome": ["google-chrome-stable", "google-chrome"],
             "msedge": ["microsoft-edge-stable", "microsoft-edge"],
             "chromium": ["chromium", "chromium-browser"]}
    return [Path(p) for p in vast[soort]] + [Path(w) for n in namen[soort] if (w := shutil.which(n))]


def browser_zoeken(keuze="auto"):
    """Pad naar Chrome, Edge of Chromium. Allemaal op Chromium gebaseerd en (op
    de Chromium van Debian/Raspberry Pi OS na) met H.264, dat Twitch nodig heeft."""
    keuze = (keuze or "auto").strip()
    soort = {"auto": None, "chrome": "chrome", "msedge": "msedge", "edge": "msedge",
             "chromium": "chromium"}.get(keuze.lower(), "pad")
    if soort == "pad":
        if Path(keuze).is_file():
            return keuze
        raise RuntimeError(f"browser niet gevonden: {keuze}")
    for s in [soort] if soort else ["chrome", "msedge", "chromium"]:
        for p in _kandidaten(s):
            if p.is_file():
                return str(p)
    raise RuntimeError("Geen Google Chrome, Microsoft Edge of Chromium gevonden. Installeer Google Chrome "
                       "of zet het pad bij 'browser' in de instellingen.")


def singletons_opruimen(profiel: Path):
    # Na een crash of herstart van de container blijven deze achter, en dan
    # weigert Chrome het profiel ("in gebruik op een andere computer").
    for f in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.unlink(profiel / f)
        except FileNotFoundError:
            pass


def auth_cookie_in_profiel(profiel: Path) -> bool:
    """Of het profiel al een Twitch-login heeft. De naam van een cookie staat
    onversleuteld in de database, de waarde niet."""
    for db in (profiel / "Default" / "Network" / "Cookies", profiel / "Default" / "Cookies"):
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                n = con.execute("select count(*) from cookies where name = 'auth-token' "
                                "and host_key like '%twitch.tv'").fetchone()[0]
            finally:
                con.close()
            if n:
                return True
        except sqlite3.Error:
            pass
    return False


def xvfb_starten():
    """Virtueel scherm voor een server zonder scherm (Docker). Een gewone,
    niet-headless browser lijkt het meest op echt kijken."""
    if sys.platform != "linux" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") \
            or not shutil.which("Xvfb"):
        return None
    for f in ("/tmp/.X99-lock", "/tmp/.X11-unix/X99"):
        try:
            os.unlink(f)
        except FileNotFoundError:
            pass
    proc = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    if proc.poll() is not None:
        raise RuntimeError("Xvfb start niet")
    os.environ["DISPLAY"] = ":99"
    return proc


def duur(seconden):
    m = int(seconden // 60)
    return f"{m // 60}u{m % 60:02d}m" if m >= 60 else f"{m} min"


# --- de kijker ---------------------------------------------------------------

class Kijker:
    """Draait in één asyncio-loop. Andere threads (de tray-app) praten ermee via
    vraag_stop, vraag_inloggen en wissel_venster."""

    def __init__(self, config_pad=None, bureaublad=None, status=None):
        self.config_pad = config_pad
        self.inst = inst_mod.laden(config_pad)
        self.melden = Melder(lambda: self.inst, bureaublad)
        self.status_cb = status or (lambda staat, tekst: None)
        self.status_tekst = "Opstarten"
        self.staat = "opstarten"
        # De tray-app werkt zelf bij; zonder tray meldt de kijker nieuwe versies.
        self.updates_melden = True
        self.inloggen_bij_start = False
        self.account = None  # Twitch-login zodra het token gecontroleerd is
        self._herstart = False  # browser opnieuw starten (tonen of verbergen)
        self._update_check, self._update_gemeld = 0.0, None
        self.zichtbaar = not self.inst.browser_verbergen
        self.loop = self.pw = self.ctx = self.page = self.xvfb = None
        self.geen_scherm = False  # Linux zonder scherm en zonder Xvfb
        self._stoppen = self._inloggen = False
        self._wekker = None
        self._configfout = None

    # aanroepen vanuit een andere thread

    def _van_buiten(self, functie):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(functie)

    def vraag_stop(self):
        def f():
            self._stoppen = True
            self._wekker.set()
        self._van_buiten(f)

    def vraag_inloggen(self):
        def f():
            self._inloggen = True
            self._wekker.set()
        self._van_buiten(f)

    def wissel_venster(self):
        """Browser tonen of verbergen. Kijkt hij al, dan start de browser opnieuw."""
        self.zichtbaar = not self.zichtbaar

        def f():
            if self.ctx:
                self._herstart = True
                self._wekker.set()
        self._van_buiten(f)

    # hulpjes

    async def pauze(self, seconden):
        """Wacht, maar houdt meteen op bij stoppen of inloggen. Geeft True als de
        lopende taak moet ophouden."""
        try:
            await asyncio.wait_for(self._wekker.wait(), timeout=seconden)
        except asyncio.TimeoutError:
            pass
        self._wekker.clear()
        return self._stoppen or self._inloggen or self._herstart

    def status(self, staat, tekst, **velden):
        # status.json is ook de hartslag voor de healthcheck in Docker.
        self.status_tekst, self.staat = tekst, staat
        self.status_cb(staat, tekst)
        velden.update(staat=staat, tekst=tekst, bijgewerkt=datetime.now().isoformat(timespec="seconds"))
        try:
            self.inst.data.mkdir(parents=True, exist_ok=True)
            tmp = self.inst.status_pad.with_suffix(".tmp")
            tmp.write_text(json.dumps(velden, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.inst.status_pad)
        except OSError as e:
            log(f"status schrijven mislukt: {e}")

    def instellingen_herladen(self):
        try:
            nieuw = inst_mod.laden(self.config_pad)
        except Exception as e:
            if str(e) != self._configfout:
                self._configfout = str(e)
                self.melden(f"⚠️ Fout in de instellingen, ik werk door met de vorige: {e}")
            return
        self._configfout = None
        if nieuw.kanalen != self.inst.kanalen:
            log(f"kanalen: {', '.join(nieuw.kanalen)}")
        self.inst = nieuw

    # browser

    async def browser_starten(self, gebruiker):
        exe = browser_zoeken(self.inst.browser)
        self.inst.profiel.mkdir(parents=True, exist_ok=True)
        singletons_opruimen(self.inst.profiel)
        # Op een virtueel scherm (Docker) een gewone browser. Op een echte computer
        # zonder venster (headless), tenzij je hem wilt zien: een venster kan op
        # Windows de focus van je spel pakken.
        headless = self.geen_scherm or (not self.xvfb and not self.zichtbaar)
        ctx = await self.pw.chromium.launch_persistent_context(
            str(self.inst.profiel),
            executable_path=exe,
            headless=headless,
            args=CHROME_ARGS,
            viewport={"width": 1280, "height": 720},
            locale="en-US",  # knopteksten als "Claim Now" en "Reject" zijn dan voorspelbaar
        )
        if gebruiker:
            twilight = {"authToken": self.inst.token, "displayName": gebruiker["displayName"],
                        "id": gebruiker["id"], "login": gebruiker["login"],
                        "roles": {"isStaff": False}, "version": 2}
            koekjes = {"auth-token": self.inst.token, "login": gebruiker["login"],
                       "twilight-user": urllib.parse.quote(json.dumps(twilight, separators=(",", ":")))}
            await ctx.add_cookies([
                {"name": n, "value": w, "domain": ".twitch.tv", "path": "/", "secure": True,
                 "sameSite": "Lax", "expires": time.time() + 365 * 86400}
                for n, w in koekjes.items()
            ])
        await ctx.add_init_script(INIT_SCRIPT)
        self.ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        return ctx

    async def _klik_als_er(self, page, selector, naam=None, timeout=3000):
        loc = page.locator(selector)
        if naam:
            loc = loc.filter(has_text=naam)
        try:
            if await loc.count():
                await loc.first.click(timeout=timeout)
                return True
        except PWError:
            pass
        return False

    async def schermen_wegklikken(self, page):
        # Cookiebanner: alleen het noodzakelijke.
        if await self._klik_als_er(page, '[data-a-target="consent-banner"] button',
                                   re.compile(r"^\s*Reject\s*$", re.I)):
            log("cookiebanner weggeklikt (Reject)")
        # Leeftijds- of inhoudswaarschuwing voor de speler.
        for sel in ('[data-a-target="content-classification-gate-overlay-start-watching-button"]',
                    '[data-a-target="player-overlay-mature-accept"]'):
            if await self._klik_als_er(page, sel):
                log("waarschuwing voor de speler weggeklikt")

    @staticmethod
    async def ingelogd(page):
        try:
            await page.wait_for_selector('[data-a-target="top-nav-container"]', timeout=30000)
            await page.wait_for_timeout(3000)
        except PWError:
            pass
        return await page.locator('[data-a-target="login-button"]').count() == 0

    async def kanaal_openen(self, login):
        await self.page.goto(f"https://www.twitch.tv/{login}", wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_selector("video", state="attached", timeout=45000)
        await self.page.wait_for_timeout(3000)
        await self.schermen_wegklikken(self.page)

    async def speler_staat(self):
        try:
            return await self.page.evaluate(SPELER_JS)
        except PWError:
            return None

    async def speler_bijsturen(self, st):
        """Zorgt dat de speler speelt en niet gedempt is. Geeft True als de pagina
        opnieuw geladen moet worden."""
        page = self.page
        try:
            await page.hover('[data-a-target="video-player"]', timeout=5000)
        except PWError:
            pass
        if st["muted"]:
            knop = page.locator('[data-a-target="player-mute-unmute-button"]')
            try:
                label = (await knop.get_attribute("aria-label", timeout=5000)) or ""
                if label.lower().startswith("unmute"):
                    await knop.click(timeout=5000)
                    log("speler stond gedempt: geluid weer aan")
            except PWError as e:
                log(f"dempknop niet gevonden: {e.message.splitlines()[0]}")
        elif st["volume"] == 0:
            log("volume stond op 0: pagina opnieuw laden")  # het init-script zet het op 0.5
            return True
        if st["paused"]:
            knop = page.locator('[data-a-target="player-play-pause-button"]')
            try:
                label = (await knop.get_attribute("aria-label", timeout=5000)) or ""
                if label.lower().startswith("play"):
                    await knop.click(timeout=5000)
                    log("speler stond op pauze: weer gestart")
            except PWError:
                await page.evaluate("() => document.querySelector('video')?.play()")
        return False

    async def laagste_kwaliteit(self):
        page = self.page
        try:
            await page.hover('[data-a-target="video-player"]', timeout=5000)
            await page.click('[data-a-target="player-settings-button"]', timeout=5000)
            await page.click('[data-a-target="player-settings-menu-item-quality"]', timeout=5000)
            opties = page.locator('[data-a-target="player-settings-submenu-quality-option"]')
            n = await opties.count()
            if n:
                await opties.nth(n - 1).click(timeout=5000)  # de laagste staat onderaan
                log("kwaliteit op de laagste stand gezet")
        except PWError as e:
            log(f"kwaliteit instellen lukte niet: {e.message.splitlines()[0]}")
        finally:
            await page.keyboard.press("Escape")

    async def _achtergrondtab(self, url):
        """Nieuw tabblad dat niet naar voren komt: de stream blijft het actieve
        tabblad en het venster springt niet open tijdens het gamen."""
        try:
            cdp = await self.ctx.new_cdp_session(self.page)
            async with self.ctx.expect_page(timeout=15000) as nieuw:
                await cdp.send("Target.createTarget", {"url": url, "background": True})
            await cdp.detach()
            page = await nieuw.value
            await page.wait_for_load_state("domcontentloaded", timeout=60000)
        except PWError as e:
            log(f"tabblad op de achtergrond lukte niet, gewoon nieuw tabblad: {e.message.splitlines()[0]}")
            page = await self.ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return page

    @staticmethod
    async def _knop_weg(page, knoppen, n, seconden=15):
        for _ in range(seconden):
            await page.wait_for_timeout(1000)
            if await knoppen.count() < n:
                return True
        return False

    async def drops_ophalen(self):
        """Opent de inventaris in een tabblad op de achtergrond en klikt alle
        claimknoppen. Geeft (opgehaald, niet_gelukt, voortgang)."""
        page = await self._achtergrondtab(INVENTARIS_URL)
        opgehaald, niet_gelukt = [], []
        try:
            await page.wait_for_timeout(8000)  # de inventaris laadt zijn lijst pas na de pagina
            await self.schermen_wegklikken(page)
            if await page.locator('[data-a-target="login-button"]').count():
                raise NietIngelogd()
            knoppen = page.get_by_role("button", name=re.compile(CLAIMKNOP, re.I))
            for _ in range(20):
                n = await knoppen.count()
                if not n:
                    break
                knop = knoppen.first
                naam = await knop.evaluate(DROPNAAM_JS)
                gelukt = False
                # Eerst een gewone klik, dan een klik via JavaScript als vangnet
                # voor een tabblad op de achtergrond.
                for klik in (lambda: knop.click(timeout=10000, force=True), lambda: knop.evaluate("b => b.click()")):
                    try:
                        await klik()
                    except PWError:
                        continue
                    if gelukt := await self._knop_weg(page, knoppen, n):
                        break
                if not gelukt:
                    # Twitch werkt de lijst soms pas later bij: vers laden en opnieuw tellen.
                    await page.reload(wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(8000)
                    gelukt = await knoppen.count() < n
                if not gelukt:
                    niet_gelukt.append(naam)
                    break
                opgehaald.append(naam)
            voortgang = await page.evaluate(VOORTGANG_JS)
        finally:
            await page.close()
        return opgehaald, niet_gelukt, voortgang

    # de lussen

    async def kijken(self, gebruiker, login, naam, titel, game, stil=False):
        """Kijkt tot het kanaal offline gaat of een hoger kanaal live komt.
        stil: na een herstart van de browser niet opnieuw melden dat hij live is."""
        if not stil:
            self.melden(f"🔴 **{naam}** is live ({game}): {titel}\nIk kijk mee.")
        begin = time.monotonic()
        await self.browser_starten(gebruiker)
        reden, voortgang, claim_gemeld = "offline", [], set()
        st = None

        def claims_melden(opgehaald, niet_gelukt):
            for d in opgehaald:
                self.melden(f"🎁 Drop opgehaald: {d}")
            nieuw = set(niet_gelukt) - claim_gemeld
            if nieuw:
                claim_gemeld.update(nieuw)
                self.melden(f"⚠️ Drop klaar, maar claimen lukte niet: {', '.join(nieuw)}\n"
                            f"Haal hem zelf op: {INVENTARIS_URL}")

        try:
            await self.kanaal_openen(login)
            if not await self.ingelogd(self.page):
                raise NietIngelogd()
            log(f"kijkt naar {login} als {gebruiker['login']}")

            nu = time.monotonic()
            laatste_claim = nu - self.inst.claim_minuten * 60 + 120  # eerste ronde na twee minuten
            laatste_check = laatste_herlaad = nu
            kwaliteit_gecheckt, vorige_tijd, stil = False, None, 0

            while not await self.pauze(30):
                nu = time.monotonic()

                if nu - laatste_check >= self.inst.poll:
                    laatste_check = nu
                    self.instellingen_herladen()
                    try:
                        live = await asyncio.to_thread(twitch.live_kanaal, self.inst.kanalen)
                    except Exception as e:
                        log(f"live-check mislukt, ik kijk door: {e}")
                    else:
                        if not live:
                            break
                        if live[0] != login:
                            reden = f"{live[1]} gaat voor"
                            break

                # Bij een raid stuurt Twitch je door naar een ander kanaal.
                if not self.page.url.lower().rstrip("/").endswith("/" + login):
                    log(f"pagina staat op {self.page.url}: terug naar {login}")
                    await self.kanaal_openen(login)
                    kwaliteit_gecheckt, vorige_tijd, stil = False, None, 0
                    continue

                herladen = nu - laatste_herlaad >= self.inst.herlaad_uren * 3600  # tegen geheugengroei
                st = await self.speler_staat()
                if st is None:
                    log("geen videospeler op de pagina")
                    herladen = True
                else:
                    herladen |= await self.speler_bijsturen(st)
                    if not kwaliteit_gecheckt and st["height"]:
                        kwaliteit_gecheckt = True
                        if st["height"] > 400:
                            await self.laagste_kwaliteit()
                    if not st["paused"] and st["time"] == vorige_tijd:
                        stil += 1
                        if stil >= 2:
                            log("beeld staat al een minuut stil")
                            herladen = True
                    else:
                        stil = 0
                    vorige_tijd = st["time"]

                if herladen:
                    await self.kanaal_openen(login)
                    laatste_herlaad = time.monotonic()
                    kwaliteit_gecheckt, vorige_tijd, stil = False, None, 0

                if nu - laatste_claim >= self.inst.claim_minuten * 60:
                    laatste_claim = nu
                    opgehaald, niet_gelukt, voortgang = await self.drops_ophalen()
                    claims_melden(opgehaald, niet_gelukt)
                    if voortgang:
                        log("voortgang: " + " | ".join(voortgang))

                minuten = int((nu - begin) // 60)
                # Met de voortgang erbij zie je in de tooltip dat het meetelt.
                tekst = f"Kijkt naar {naam} ({duur(nu - begin)})" + (f", {voortgang[0]}" if voortgang else "")
                self.status("kijken", tekst, kanaal=login, titel=titel, minuten=minuten, speler=st,
                            voortgang=voortgang)

            if not self._stoppen and not self._herstart:
                # Willekeurige drops vallen soms vlak voor het einde.
                opgehaald, niet_gelukt, voortgang = await self.drops_ophalen()
                claims_melden(opgehaald, niet_gelukt)
        finally:
            ctx, self.ctx, self.page = self.ctx, None, None
            try:
                await ctx.close()
            except PWError:
                pass

        if self._herstart:
            return
        if self._inloggen:
            reden = "opnieuw inloggen"
        if not self._stoppen:
            tekst = f"⚫ Gestopt met {naam} ({reden}), {duur(time.monotonic() - begin)} meegekeken."
            if voortgang:
                tekst += "\n" + "\n".join(f"- {v}" for v in voortgang)
            self.melden(tekst)

    async def hoofdlus(self):
        log(f"{NAAM} {__version__} gestart; kanalen: {', '.join(self.inst.kanalen)}")
        token_ok = None  # None = nog niet gecheckt
        gebruiker, vorig_token, laatste_tokencheck, fouten = None, None, 0.0, 0
        while not self._stoppen:
            if self._inloggen:
                self._inloggen = False
                await self.inloggen()
            self.instellingen_herladen()
            if self.inst.token != vorig_token:
                gebruiker, vorig_token = None, self.inst.token

            if not gebruiker or time.monotonic() - laatste_tokencheck >= 900:
                try:
                    gebruiker = await asyncio.to_thread(twitch.gebruiker_bij_token, self.inst.token)
                except Exception as e:
                    log(f"tokencheck mislukt (netwerk?): {e}")
                    self.status("netwerkfout", "Geen verbinding met Twitch", fout=str(e))
                    await self.pauze(self.inst.poll)
                    continue
                laatste_tokencheck = time.monotonic()
                self.account = gebruiker["login"] if gebruiker else None
                if not gebruiker:
                    if token_ok is not False:
                        self.melden(f"⚠️ Niet ingelogd bij Twitch: het token ontbreekt of werkt niet meer. {HOE_INLOGGEN}")
                    token_ok = False
                    self.status("niet-ingelogd", "Niet ingelogd bij Twitch")
                    await self.pauze(60)
                    continue
                if token_ok is not True:
                    log(f"ingelogd als {gebruiker['login']}")
                    if token_ok is False:
                        self.melden(f"✅ Ingelogd bij Twitch als {gebruiker['login']}.")
                token_ok = True

            await self.nieuwe_versie_melden()
            try:
                live = await asyncio.to_thread(twitch.live_kanaal, self.inst.kanalen)
            except Exception as e:
                log(f"live-check mislukt: {e}")
                live = None
            if not live:
                extra = f" (+{len(self.inst.kanalen) - 1})" if len(self.inst.kanalen) > 1 else ""
                self.status("wachten", f"Wacht op {self.inst.kanalen[0]}{extra}",
                            kanalen=self.inst.kanalen, account=gebruiker["login"])
                await self.pauze(self.inst.poll)
                continue

            try:
                herstart, self._herstart = self._herstart, False
                await self.kijken(gebruiker, *live, stil=herstart)
                fouten = 0
            except NietIngelogd:
                self.melden("⚠️ De browser is niet ingelogd bij Twitch, hoewel het token geldig is. "
                            "Ik probeer het over een kwartier opnieuw.")
                self.status("niet-ingelogd", "Browser niet ingelogd bij Twitch")
                await self.pauze(900)
            except Exception as e:
                if self._stoppen:
                    break
                fouten += 1
                log(f"fout tijdens kijken: {e}\n{traceback.format_exc()}")
                if fouten == 3:
                    self.melden(f"⚠️ {NAAM} loopt steeds vast tijdens het kijken: {e}")
                self.status("fout", f"Fout: {str(e)[:80]}", fout=str(e))
                await self.pauze(min(60 * fouten, 600))

    async def nieuwe_versie_melden(self):
        """Eén keer per dag kijken of er een nieuwe versie is, en die één keer melden."""
        if not self.updates_melden or self.inst.updates == "uit" \
                or time.monotonic() - self._update_check < 86400 and self._update_check:
            return
        self._update_check = time.monotonic()
        try:
            versie, _, _ = await asyncio.to_thread(bijwerken.nieuwste)
        except Exception as e:
            log(f"zoeken naar een nieuwe versie mislukt: {e}")
            return
        if bijwerken.nieuwer(versie) and versie != self._update_gemeld:
            self._update_gemeld = versie
            hoe = ("Bijwerken: `git pull && docker compose up -d --build`." if os.environ.get("DATA_DIR")
                   else "Bijwerken: `pipx upgrade drops-makker` of download de nieuwe versie.")
            self.melden(f"ℹ️ Er is een nieuwe versie van {NAAM}: {versie} (je hebt {__version__}).\n"
                        f"{bijwerken.RELEASES_URL}\n{hoe}")

    async def inloggen(self):
        """Opent een gewoon browservenster (zonder automatisering) op de inlogpagina
        van Twitch, met het profiel van drops-makker. Na het inloggen leest
        drops-makker het token uit dat profiel."""
        if self.geen_scherm or self.xvfb:
            self.melden("⚠️ Inloggen via een browservenster kan alleen op een computer met scherm. "
                        "Gebruik op een server het token (zie de README).")
            return None
        exe = browser_zoeken(self.inst.browser)
        profiel = self.inst.profiel
        profiel.mkdir(parents=True, exist_ok=True)
        singletons_opruimen(profiel)
        if auth_cookie_in_profiel(profiel):
            # Al ingelogd: eerst uitloggen, anders sluit het venster meteen
            # en kun je niet van account wisselen.
            ctx = await self.pw.chromium.launch_persistent_context(str(profiel), executable_path=exe, headless=True)
            await ctx.clear_cookies()
            await ctx.close()
            singletons_opruimen(profiel)
        welkom = self.inst.data / "inloggen.html"
        welkom.write_text(WELKOM_HTML, encoding="utf-8")
        self.status("inloggen", "Log in bij Twitch in het venster van drops-makker")
        log("log in bij Twitch in het browservenster dat nu opent")
        if self.melden.bureaublad:
            self.melden.bureaublad("Log in bij Twitch in het venster van drops-makker dat nu opent.")
        proc = subprocess.Popen([exe, f"--user-data-dir={profiel}", "--no-first-run", "--no-default-browser-check",
                                 # Dezelfde opslag voor cookies als waarmee Playwright het profiel opent.
                                 "--password-store=basic", "--use-mock-keychain", "--lang=en-US",
                                 "--window-size=1000,800", welkom.as_uri()])
        begin = time.monotonic()
        while proc.poll() is None and time.monotonic() - begin < 900 and not self._stoppen:
            await asyncio.sleep(2)
            if auth_cookie_in_profiel(profiel):
                await asyncio.sleep(3)  # Twitch zet na het inloggen nog meer cookies
                break
        if proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, 15)
            except subprocess.TimeoutExpired:
                proc.kill()

        singletons_opruimen(profiel)
        ctx = await self.pw.chromium.launch_persistent_context(str(profiel), executable_path=exe, headless=True)
        try:
            cookies = await ctx.cookies("https://www.twitch.tv")
        finally:
            await ctx.close()
        token = next((c["value"] for c in cookies if c["name"] == "auth-token"), "")
        gebruiker = await asyncio.to_thread(twitch.gebruiker_bij_token, token) if token else None
        self.account = gebruiker["login"] if gebruiker else None
        if gebruiker:
            inst_mod.token_opslaan(self.inst.data, token, gebruiker["login"])
            self.instellingen_herladen()
            self.melden(f"✅ Ingelogd bij Twitch als {gebruiker['login']}.")
        else:
            self.melden("⚠️ Inloggen bij Twitch is niet gelukt. Probeer het opnieuw.")
        return gebruiker

    async def test(self):
        """Eén keer alles nalopen: token, live-status, browser, inlog, speler en inventaris."""
        log(f"kanalen: {', '.join(self.inst.kanalen)}; browser: {browser_zoeken(self.inst.browser)}")
        log(f"meldingen: mattermost {'ja' if self.inst.mattermost else 'nee'}, "
            f"discord {'ja' if self.inst.discord else 'nee'}")
        gebruiker = await asyncio.to_thread(twitch.gebruiker_bij_token, self.inst.token)
        log(f"token: {'hoort bij ' + gebruiker['login'] if gebruiker else 'ontbreekt of ongeldig'}")
        live = await asyncio.to_thread(twitch.live_kanaal, self.inst.kanalen)
        log(f"live: {live[0] + ' - ' + live[2] if live else 'geen van de kanalen'}")
        login = live[0] if live else self.inst.kanalen[0]

        await self.browser_starten(gebruiker)
        try:
            await self.kanaal_openen(login)
            log(f"browser ingelogd: {'ja' if await self.ingelogd(self.page) else 'nee'}")
            await self.page.wait_for_timeout(10000)
            st = await self.speler_staat()
            log(f"speler: {st}")
            if live and st:
                await self.speler_bijsturen(st)
                if st["height"] > 400:
                    await self.laagste_kwaliteit()
                    await self.page.wait_for_timeout(8000)
                log(f"speler na bijsturen: {await self.speler_staat()}")
            await self.page.screenshot(path=str(self.inst.data / "test-kanaal.png"))
            if gebruiker:
                try:
                    opgehaald, niet_gelukt, voortgang = await self.drops_ophalen()
                    log(f"inventaris: opgehaald {opgehaald}, niet gelukt {niet_gelukt}")
                    log("voortgang: " + (" | ".join(voortgang) if voortgang else "niets lopend"))
                except NietIngelogd:
                    log("inventaris: niet ingelogd")
            log(f"schermafdruk: {self.inst.data / 'test-kanaal.png'}")
        finally:
            await self.ctx.close()
        return bool(gebruiker)

    async def zelftest(self):
        """Kan de browser starten en H.264 afspelen? Raakt Twitch niet aan."""
        exe = browser_zoeken(self.inst.browser)
        browser = await self.pw.chromium.launch(executable_path=exe, headless=True)
        try:
            page = await browser.new_page()
            h264 = await page.evaluate("() => MediaSource.isTypeSupported('video/mp4; codecs=\"avc1.4D401F\"')")
            log(f"{NAAM} {__version__}; browser {exe} ({browser.version}); H.264: {'ja' if h264 else 'NEE'}")
        finally:
            await browser.close()
        return bool(h264)

    async def run(self, taak="kijken"):
        """taak: kijken, inloggen, test of zelftest. Geeft True als het gelukt is."""
        self.loop = asyncio.get_running_loop()
        self._wekker = asyncio.Event()
        # Opnieuw te starten na een mislukte update; inloggen alleen bij de eerste start.
        self._stoppen, self._inloggen, self.inloggen_bij_start = False, self.inloggen_bij_start, False
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                self.loop.add_signal_handler(sig, self.vraag_stop)
            except (NotImplementedError, RuntimeError, ValueError):
                pass  # Windows, of niet in de hoofdthread
        if taak != "zelftest":
            self.xvfb = xvfb_starten()
            self.geen_scherm = sys.platform == "linux" and not os.environ.get("DISPLAY") \
                and not os.environ.get("WAYLAND_DISPLAY")
        try:
            async with async_playwright() as pw:
                self.pw = pw
                if taak == "kijken":
                    await self.hoofdlus()
                    return True
                if taak == "inloggen":
                    return bool(await self.inloggen())
                if taak == "test":
                    return await self.test()
                return await self.zelftest()
        finally:
            if self.xvfb:
                self.xvfb.terminate()
            if taak == "kijken":
                self.status("gestopt", "Gestopt")
                log("gestopt")

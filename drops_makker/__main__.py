"""drops-makker starten.

    drops-makker              kijken (Windows-app: met icoon in het systeemvak)
    drops-makker --inloggen   inloggen bij Twitch in een browservenster
    drops-makker --test       één keer alles nalopen en stoppen
    drops-makker --zelftest   alleen controleren of de browser werkt
    drops-makker --config PAD ander instellingenbestand
    drops-makker --bijwerken-van PAD   Windows-app bijwerken met een gedownloade exe
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from . import NAAM, __version__, bijwerken
from . import instellingen as inst_mod
from .logboek import log, naar_bestand


def enkele_instantie(data, wachten=0):
    """Houdt een slot vast zolang drops-makker draait; None als er al een draait.
    Twee kijkers op hetzelfde browserprofiel gaat mis. Na een update wacht de
    nieuwe versie tot de oude weg is."""
    data.mkdir(parents=True, exist_ok=True)
    f = open(data / "draait.lock", "a+")
    einde = time.monotonic() + wachten
    while True:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.monotonic() >= einde:
                f.close()
                return None
            time.sleep(1)


def main():
    p = argparse.ArgumentParser(prog=NAAM, description="Kijkt Twitch-streams automatisch mee voor drops.")
    p.add_argument("--inloggen", action="store_true", help="inloggen bij Twitch in een browservenster")
    p.add_argument("--test", action="store_true", help="één keer alles nalopen en stoppen")
    p.add_argument("--zelftest", action="store_true", help="alleen controleren of de browser werkt")
    p.add_argument("--tray", action="store_true", help="met icoon in het systeemvak")
    p.add_argument("--console", action="store_true", help="zonder icoon, logboek in de terminal")
    p.add_argument("--config", help="pad naar instellingen.toml")
    p.add_argument("--bijwerken-van", metavar="PAD", help="Windows-app bijwerken met een gedownloade exe")
    p.add_argument("--na-update", metavar="VERSIE", help=argparse.SUPPRESS)
    p.add_argument("--versie", action="version", version=f"{NAAM} {__version__}")
    args = p.parse_args()

    data = inst_mod.data_map()
    # De Windows-app heeft geen console: alles naar het logboek.
    if sys.stdout is None or (getattr(sys, "frozen", False) and sys.platform == "win32"):
        naar_bestand(data / f"{NAAM}.log")

    if bijwerken.kan_zichzelf_bijwerken():
        if args.na_update:
            log(f"bijgewerkt van {args.na_update} naar {__version__}")
        bijwerken.oud_opruimen(wachten=30 if args.na_update else 0)

    if args.bijwerken_van:
        if not bijwerken.kan_zichzelf_bijwerken():
            log("alleen de Windows-app kan zichzelf bijwerken")
            sys.exit(1)
        nieuw = bijwerken.klaarzetten(Path(args.bijwerken_van))
        bijwerken.installeren(nieuw, extra_args=[a for a in ("--zelftest", "--console") if getattr(args, a[2:])])
        return

    taak = "inloggen" if args.inloggen else "test" if args.test else "zelftest" if args.zelftest else "kijken"
    tray = taak == "kijken" and (args.tray or (sys.platform == "win32" and getattr(sys, "frozen", False)
                                               and not args.console))

    slot = None
    if taak in ("kijken", "inloggen"):
        slot = enkele_instantie(data, wachten=60 if args.na_update else 0)
        if slot is None:
            log(f"{NAAM} draait al")
            sys.exit(1)

    if tray:
        from .tray import main as tray_main
        tray_main(args.config, na_update=args.na_update)
        return

    if taak == "kijken" and args.config is None and not os.environ.get("DATA_DIR"):
        if inst_mod.voorbeeld_schrijven(inst_mod.standaard_config()):
            log(f"instellingen aangemaakt: {inst_mod.standaard_config()}")

    from .kijker import Kijker
    try:
        kijker = Kijker(args.config)
    except ValueError as e:
        log(f"fout in de instellingen: {e}")
        sys.exit(2)
    gelukt = asyncio.run(kijker.run(taak))
    sys.exit(0 if gelukt else 1)


if __name__ == "__main__":
    main()

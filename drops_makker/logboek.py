import sys
from datetime import datetime
from pathlib import Path


def log(tekst):
    regel = f"{datetime.now():%Y-%m-%d %H:%M:%S} {tekst}"
    if sys.stdout:
        try:
            print(regel, flush=True)
        except (OSError, ValueError):
            pass


def naar_bestand(pad: Path):
    """Stuurt stdout en stderr naar een logbestand. Voor de Windows-app, die geen
    console heeft. Bij meer dan 5 MB gaat het oude logboek naar .1.log."""
    pad.parent.mkdir(parents=True, exist_ok=True)
    if pad.exists() and pad.stat().st_size > 5_000_000:
        pad.replace(pad.with_suffix(".1.log"))
    f = open(pad, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    return f

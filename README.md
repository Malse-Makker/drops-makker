# drops-makker

Kijkt Twitch-streams automatisch mee voor drops, zodat je er niets van mist als
je er zelf niet bij bent. Gemaakt voor de War Thunder-drops op
[WarThunder_Esports](https://www.twitch.tv/warthunder_esports), maar het werkt
voor elk kanaal met drops.

Draait als app op Windows (icoon in het systeemvak), in Docker op een server of
Raspberry Pi, of gewoon met Python.

## Hoe het werkt

- Elke minuut vraagt drops-makker aan Twitch welke van jouw kanalen live zijn.
  Zolang er niets live is, draait er geen browser.
- Gaat er een kanaal live, dan opent een echte browser (Chrome, Edge of
  Chromium) dat kanaal, ingelogd met jouw account. De speler staat **aan met
  geluid**, maar de browser zelf is gedempt, net als een gedempt tabblad. Een
  gedempte speler telt namelijk niet mee voor drops.
- Je kunt meerdere kanalen opgeven. drops-makker kijkt altijd naar het
  **bovenste kanaal dat live is**. Gaat een hoger kanaal live, dan stapt hij
  daarnaar over.
- De kwaliteit gaat naar de laagste stand (160p): weinig bandbreedte en cpu.
- Elk kwartier, en nog een keer als de stream stopt, opent hij je
  [inventaris](https://www.twitch.tv/drops/inventory) in een tabblad op de
  achtergrond en klikt hij op alle *Claim*-knoppen.
- Hij houdt de speler in de gaten: gedempt, op pauze of stilstaand beeld wordt
  hersteld, en na een raid gaat hij terug naar het kanaal.
- Meldingen (live, drop opgehaald, token verlopen) kunnen naar Mattermost,
  Discord en, op Windows, rechtsonder in beeld.

## Eerst: je game-account koppelen

Zonder koppeling krijg je geen drops, ook niet met drops-makker. Ga op Twitch
naar [Drops-campagnes](https://www.twitch.tv/drops/campaigns), zoek je game en
klik *Connect*. Voor War Thunder koppel je zo je Gaijin-account.

## Windows

1. Download `drops-makker.exe` bij de nieuwste
   [release](https://github.com/Malse-Makker/drops-makker/releases/latest).
   Je hebt Google Chrome of Microsoft Edge nodig. Edge zit standaard in Windows.
2. Start het. Windows waarschuwt misschien ("Windows heeft uw pc beschermd"),
   omdat de app niet ondertekend is: kies *Meer info* → *Toch uitvoeren*.
3. Er opent een browservenster: log daar in bij Twitch. Zodra je bent
   ingelogd, sluit het venster vanzelf.
4. drops-makker staat nu als paars icoon in het systeemvak (rechtsonder, soms
   onder het pijltje). Via dat icoon:
   - **Instellingen openen**: je kanalen en meldingen (zie hieronder).
   - **Start met Windows**: automatisch starten als je inlogt.
   - **Browser tonen**: het browservenster laten zien. Standaard staat het
     geminimaliseerd.
   - **Inloggen bij Twitch**: opnieuw inloggen, bijvoorbeeld met een ander
     account.
   - **Logboek openen**: zien wat hij doet.
   - **Zoeken naar updates**: meteen kijken of er een nieuwe versie is.

drops-makker werkt zichzelf bij. Een halve minuut na het opstarten, en daarna
elke zes uur, kijkt hij of hier een nieuwe release staat. Zo ja, dan
downloadt hij die, controleert de controlesom en herstart hij in de nieuwe
versie. Dat doet hij nooit midden in een stream. Wil je dat niet, zet dan
`updates = "melden"` (alleen een melding) of `"uit"` in de instellingen. Heb je
versie 1.0.0, download dan één keer zelf de nieuwe versie; die kon zichzelf nog
niet bijwerken.

Instellingen staan in `%APPDATA%\drops-makker\instellingen.toml`, het
browserprofiel en het logboek in `%LOCALAPPDATA%\drops-makker`.

## Docker (server of Raspberry Pi)

Werkt op amd64 en arm64, dus ook op een Raspberry Pi 4 of 5 met een 64-bit
besturingssysteem.

```bash
git clone https://github.com/Malse-Makker/drops-makker.git
cd drops-makker
cp .env.example .env
nano .env   # token en kanalen invullen
docker compose run --rm drops-makker drops-makker --test
docker compose up -d --build
```

`--test` loopt alles één keer na: token, live-status, of de browser ingelogd
is, de speler en de inventaris (met de lopende voortgang).

Volgen wat hij doet:

```bash
docker logs -f drops-makker
docker exec drops-makker cat /data/status.json
```

Na het wijzigen van `.env` is `docker compose up -d` nodig: een herstart leest
`.env` niet opnieuw. Is er een nieuwe versie, dan krijg je een melding;
bijwerken gaat met `git pull && docker compose up -d --build`.

### Het token

Op een server is er geen scherm om in te loggen. Daar gebruik je het cookie
`auth-token` van twitch.tv:

1. Open een **privévenster**, ga naar twitch.tv en log in.
2. Druk F12 en open de cookies van `https://www.twitch.tv`:
   - Chrome/Edge: tabblad *Application* → *Cookies*.
   - Firefox: tabblad *Storage* → *Cookies*.
3. Typ `auth-token` in het filtervak en kopieer de waarde (zo'n 30 tekens).
4. Sluit het privévenster **zonder uit te loggen**. Uitloggen maakt het token
   ongeldig.

Behandel het token als een wachtwoord: het geeft toegang tot je Twitch-account.
Werkt het niet meer (wachtwoord gewijzigd, overal uitgelogd), dan meldt
drops-makker dat en haal je op dezelfde manier een nieuw token.

## Met Python (Linux, macOS)

Python 3.11 of nieuwer en Google Chrome, Edge of Chromium.

```bash
pipx install git+https://github.com/Malse-Makker/drops-makker.git
drops-makker --inloggen   # browservenster om in te loggen bij Twitch
drops-makker              # kijken; Ctrl+C om te stoppen
```

De instellingen staan in `~/.config/drops-makker/instellingen.toml`. Zonder
scherm (bijvoorbeeld via ssh) gebruik je het token, zie hierboven, en
installeer je ook `xvfb`.

Gebruik je Chromium, check dan met `drops-makker --zelftest` of die H.264 kan
afspelen. De Chromium van Debian en Raspberry Pi OS kan dat; sommige andere
builds niet, en dan telt Twitch niets.

## Instellingen

Op Windows en met Python staan ze in `instellingen.toml`; wijzigingen worden
binnen een minuut vanzelf opgepakt.

```toml
kanalen = [
    "https://www.twitch.tv/warthunder_esports",   # bovenste heeft voorrang
    "https://www.twitch.tv/warthunder_esports_de",
]

[meldingen]
mattermost = ""   # incoming webhook
discord = ""      # webhook (Serverinstellingen → Integraties → Webhooks)
windows = true    # meldingen rechtsonder in Windows
```

In Docker gaat alles via `.env`:

| Variabele | Standaard | Wat |
|---|---|---|
| `TWITCH_AUTH_TOKEN` | — | het token, zie hierboven |
| `CHANNELS` | `warthunder_esports` | kanalen (links of namen) met komma's ertussen; de eerste heeft voorrang |
| `MATTERMOST_WEBHOOK` | leeg | incoming webhook van Mattermost |
| `DISCORD_WEBHOOK` | leeg | webhook van Discord |
| `POLL_SECONDS` | 60 | hoe vaak checken of een kanaal live is |
| `CLAIM_MINUTES` | 15 | hoe vaak de inventaris nalopen tijdens het kijken |
| `RELOAD_HOURS` | 3 | pagina af en toe vers laden tegen geheugengroei |
| `UPDATES` | `auto` | `melden` of `uit`: wel of geen melding bij een nieuwe versie |

## Goed om te weten

- Automatisch kijken mag officieel niet volgens de voorwaarden van Twitch. Met
  één account dat één stream kijkt is de kans op problemen klein, maar niet nul.
  Gebruik is voor eigen risico.
- Zelf tegelijk kijken met hetzelfde account kan gewoon; je krijgt de minuten
  alleen niet dubbel.
- Lukt het claimen een keer niet, dan meldt drops-makker dat. De drop blijft in
  je inventaris staan en je kunt hem zelf ophalen.
- Eén drops-makker per account: twee kijkers met hetzelfde account op
  verschillende kanalen zitten elkaar in de weg.

## Licentie

[MIT](LICENSE)

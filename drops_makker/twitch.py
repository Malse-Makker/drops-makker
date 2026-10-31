"""Twitch zonder browser: token controleren en kijken wie er live is."""
import json
import urllib.error
import urllib.request

GQL_URL = "https://gql.twitch.tv/gql"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
# De publieke client-id van twitch.tv zelf; het auth-token hoort bij deze id.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def gql(query):
    req = urllib.request.Request(
        GQL_URL,
        data=json.dumps({"query": query}).encode(),
        headers={"Client-Id": CLIENT_ID, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(f"GQL-fout: {body['errors']}")
    return body.get("data") or {}


def gebruiker_bij_token(token):
    """Het Twitch-account achter het token, of None als het token niet (meer) werkt."""
    if not token:
        return None
    req = urllib.request.Request(VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            info = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None
        raise
    gebruiker = {"id": info["user_id"], "login": info["login"], "displayName": info["login"]}
    try:
        u = gql(f'query{{user(id:"{gebruiker["id"]}"){{displayName}}}}').get("user")
        if u and u.get("displayName"):
            gebruiker["displayName"] = u["displayName"]
    except Exception:
        pass
    return gebruiker


def live_kanaal(kanalen):
    """Het eerste kanaal uit de lijst dat live is, als (login, naam, titel, game), of None.
    De namen zijn al gecontroleerd door instellingen.kanaal_uit."""
    delen = " ".join(
        f'c{i}:user(login:"{k}"){{login displayName stream{{id title game{{name}}}}}}'
        for i, k in enumerate(kanalen)
    )
    data = gql("query{" + delen + "}")
    for i in range(len(kanalen)):
        u = data.get(f"c{i}")
        if u and u.get("stream"):
            s = u["stream"]
            return u["login"], u["displayName"], s.get("title") or "", (s.get("game") or {}).get("name") or ""
    return None

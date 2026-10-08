# Captain Hook v12 = v11 + nightly results recap (RECAP_ENABLED=false turns the recap off)
import requests, time, os, unicodedata, re
from datetime import datetime, timezone, timedelta
from collections import defaultdict


# ===== MATCHUP / H2H STATS (API-Football) =====

KEY = os.getenv("API_FOOTBALL_KEY")
SEASON = os.getenv("SEASON", "2026")
EDGE_PCT = float(os.getenv("EDGE_PCT", "0.10"))  # gap needed, as % of the line
MIN_EDGE = float(os.getenv("MIN_EDGE", "2"))     # but never less than this many passes
CAP = int(os.getenv("DAILY_CAP", "90"))       # max API calls per UTC day (Pro: 5000)
H2H_GAMES = int(os.getenv("H2H_GAMES", "3"))
SUB_RATE = float(os.getenv("SUB_RATE", "0.5"))        # flag if subbed off in at least this share of appearances
SUB_MIN_APPS = int(os.getenv("SUB_MIN_APPS", "4"))    # needs this many appearances to judge
SUB_AVG_MIN = float(os.getenv("SUB_AVG_MIN", "70"))   # or if the average minutes per appearance is below this
MATCHUP = os.getenv("MATCHUP_ENABLED", "true").lower() == "true"   # false = line alerts only, no API-Football calls
LAST5_ALL = os.getenv("LAST5_ALL", "false").lower() == "true"      # true = show last-5 passes on every line (more calls)
RECENT_CHECK = os.getenv("RECENT_CHECK", "true").lower() == "true"  # hold back a 🔥/🧊 if recent games disagree with it
RECENT_AGREE = float(os.getenv("RECENT_AGREE", "0.5"))              # share of recent games that must be on the lean side
FORM_GAMES = int(os.getenv("FORM_GAMES", "5"))                     # how many recent team games to look at (red-card games get left out)
MAX_GAP_RATIO = float(os.getenv("MAX_GAP_RATIO", "0.5"))            # projection more than this far from the line = data problem, no tag
LEAGUE_CHECK_ON_START = os.getenv("LEAGUE_CHECK_ON_START", "true").lower() == "true"
LEAGUE_CHECK = os.getenv(
    "LEAGUE_CHECK",
    "England:Premier League,Spain:La Liga,Italy:Serie A,Germany:Bundesliga,France:Ligue 1,"
    "Brazil:Serie A,USA:Major League Soccer,Netherlands:Eredivisie,Portugal:Primeira Liga,"
    "World:UEFA Champions League,World:UEFA Nations League,World:World Cup - Qualification Europe")
BASE = "https://v3.football.api-sports.io"

_cache = {}
_last_err = {}
_calls = {"day": None, "n": 0}
_suppressed = {"n": 0}        # picks held back this sweep because recent games disagreed
_locked = {"until": 0.0}      # set when the free plan blocks the season, so we stop wasting calls


CALL_SPACING = float(os.getenv("CALL_SPACING", "6.5"))   # seconds between calls; free plan = 10/min. On Pro use 0.3
_last = {"t": 0.0}


def _season_locked():
    return time.time() < _locked["until"]


def _get(path, params):
    if "season" in params and _season_locked():
        raise RuntimeError("free plan: season locked")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _calls["day"] != today:
        _calls["day"], _calls["n"] = today, 0
    if _calls["n"] >= CAP:
        raise RuntimeError("daily call cap reached")
    wait = CALL_SPACING - (time.time() - _last["t"])
    if wait > 0:
        time.sleep(wait)
    _last["t"] = time.time()
    _calls["n"] += 1
    r = requests.get(BASE + path, headers={"x-apisports-key": KEY},
                     params=params, timeout=15)
    if r.status_code == 429:
        _calls["n"] -= 1
        raise RuntimeError("429 rate limit: too many calls per minute")
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        msg = str(j["errors"])
        if "Free plans" in msg:
            _locked["until"] = time.time() + 1800
        raise RuntimeError(msg)
    return j.get("response", [])


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]
    try:
        val, ttl = fn(), 12 * 3600
        _last_err.pop(key, None)
    except Exception as e:
        print("stats error:", key[0], e)
        _last_err[key] = str(e)
        val, ttl = None, (600 if ("429" in str(e) or "cap" in str(e)) else 3600)
    _cache[key] = (time.time() + ttl, val)
    return val


def status():
    """Startup check: shows plan and usage."""
    if not KEY:
        return "API-Football: no key set (matchup alerts OFF)"
    try:
        r = requests.get(BASE + "/status", headers={"x-apisports-key": KEY}, timeout=15)
        d = r.json().get("response", {})
        plan = d.get("subscription", {}).get("plan", "?")
        req = d.get("requests", {})
        try:                                  # sync our counter with the real usage, so restarts can't overshoot the daily limit
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if _calls["day"] != today:
                _calls["day"], _calls["n"] = today, 0
            _calls["n"] = max(_calls["n"], int(req.get("current") or 0))
        except (TypeError, ValueError):
            pass
        return f"API-Football plan: {plan}, used {req.get('current')}/{req.get('limit_day')} today"
    except Exception as e:
        return f"API-Football status check failed: {e}"


ALIASES = {"turkiye": "Turkey", "türkiye": "Turkey", "bosnia and herzegovina": "Bosnia & Herzegovina",
           "united states": "USA", "usmnt": "USA", "uswnt": "USA", "south korea": "South Korea",
           "czechia": "Czech Republic", "n. ireland": "Northern Ireland",
           "rep. of ireland": "Ireland", "republic of ireland": "Ireland"}   # PrizePicks vs API-Football spellings (extend as needed)


def _clean(s):
    """API-Football search only accepts plain letters and spaces. Strip accents, periods, hyphens, &, etc."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip()


def _team_id(name):
    alias = ALIASES.get(name.lower())
    for q in ([alias] if alias else []) + [name, max(name.split(), key=len)]:
        q = _clean(q)
        if len(q) < 3:
            continue
        res = _get("/teams", {"search": q})
        if res:
            for t in res:
                if _clean(t["team"]["name"]).lower() == q.lower():
                    return t["team"]["id"]
            return res[0]["team"]["id"]
    return None


_STOP = {"fc", "sc", "ec", "cf", "ac", "as", "fk", "sk", "cd", "ca", "club", "the", "de", "da", "do"}


def _team_like(a, b):
    """True if two team names look like the same club (PrizePicks vs API-Football spellings)."""
    ta = {w for w in _clean(a).lower().split() if w not in _STOP and len(w) >= 3}
    tb = {w for w in _clean(b).lower().split() if w not in _STOP and len(w) >= 3}
    if ta & tb:
        return True
    return any(len(x) >= 4 and len(y) >= 4 and (x in y or y in x) for x in ta for y in tb)


def _pdata(pid):
    """A player's season stats (cached, so checking a club and reading stats cost one call)."""
    data = _cached(("pdata", pid), lambda: _get("/players", {"id": pid, "season": SEASON}))
    if data is None:
        raise RuntimeError("daily call cap or rate limit hit while reading player stats")
    return data


def _pick_by_team(cands, team):
    """Several players share this name: keep the one whose season stats include PrizePicks' team."""
    for pl in cands[:4]:
        for s in (_pdata(pl["id"]) or [{}])[0].get("statistics", []):
            if _team_like(team, (s.get("team") or {}).get("name") or ""):
                return pl
    return None


def _scan(cands, first, last, one_name):
    """Sort API profile candidates into: first name really matches, only the initial matches, or one-name hits."""
    exact, initial_only, singles = [], [], []
    for p in cands:
        pl = p["player"]
        fn = _clean(pl.get("firstname") or "").lower()
        ln = _clean(pl.get("lastname") or "").lower()
        nm = _clean(pl.get("name") or "").lower()
        ln_tail = ln.split()[-1] if ln else ""    # "De Bruyne" -> "bruyne", "van Dijk" -> "dijk"
        ln_head = ln.split()[0] if ln else ""     # "Saldivia Vazquez" -> "saldivia" (Spanish double surnames)
        nm_tail = nm.split()[-1] if nm else ""
        if one_name:
            if last in (fn, ln, nm):              # Rodri, Pedri, most Brazilians
                singles.append(pl)
            continue
        if (ln == last or ln_tail == last or ln_head == last) and fn[:1] == first[:1]:
            fn0 = fn.split()[0] if fn else ""
            if fn0 and (fn0 == first or fn0.startswith(first) or first.startswith(fn0)):
                exact.append(pl)                  # first name really matches (Elliot = Elliot, Alex = Alexander)
            else:
                initial_only.append(pl)           # only the first letter matches
        elif nm_tail == last and nm[:1] == first[:1]:
            initial_only.append(pl)
    return exact, initial_only, singles


def _player(name, team=""):
    if _season_locked():
        raise RuntimeError("free plan: season locked")      # don't spend a call on a lookup that will be blocked
    parts = _clean(name).split()
    if not parts or len(parts[-1]) < 3:
        return None
    one_name = len(parts) == 1                    # Rodri, Pedri, most Brazilians
    first, last = parts[0].lower(), parts[-1].lower()
    cands = _get("/players/profiles", {"search": last})
    exact, initial_only, singles = _scan(cands, first, last, one_name)
    if not one_name and not exact and len(parts) >= 2:
        # common surnames (Santos, Silva, Souza) fill the first page with the wrong people: try the full name once
        try:
            more = _get("/players/profiles", {"search": " ".join(parts)})
        except RuntimeError as e:
            if "cap" in str(e) or "429" in str(e) or "season locked" in str(e):
                raise                             # real limits: let the caller retry later, don't cache "not found"
            more = []                             # API rejected this search style: keep the first result as is
        if more:
            cands = cands + more
            exact, initial_only, singles = _scan(cands, first, last, one_name)
    chosen = None
    pool = singles if one_name else exact
    if len(pool) > 1 and team:                    # same name, different players: the club decides
        chosen = _pick_by_team(pool, team)
    elif pool:
        chosen = pool[0]
    elif not one_name and len(initial_only) == 1:   # accept an initial-only match only if there is exactly one
        chosen = initial_only[0]
    if not chosen:
        print("player not matched:", name, [(c["player"].get("firstname"), c["player"].get("lastname"),
                                              c["player"].get("name")) for c in cands][:8],
              f"(same-name players: {len(pool)}, initial-only: {len(initial_only)}, team wanted: {team})")
        return None
    pid = chosen["id"]
    print("player matched:", name, "->", chosen.get("firstname"), chosen.get("lastname"), "id", pid)
    data = _pdata(pid)
    passes = mins = apps = sub_out = 0
    pos = ""
    blocks = []
    for s in (data[0]["statistics"] if data else []):
        pos = pos or (s["games"].get("position") or "")
        pt = (s.get("passes") or {}).get("total")
        mn = s["games"]["minutes"] or 0
        blocks.append(((s.get("league") or {}).get("name"), mn, pt))
        if not pt:                                # no passing data for this competition: skip its minutes too,
            continue                              # otherwise his passes per 90 comes out far too low
        passes += pt
        mins += mn
        apps += s["games"].get("appearences") or 0
        sub_out += (s.get("substitutes") or {}).get("out") or 0
    print("player stats:", name, "position:", pos or "?", "(league, minutes, passes)", blocks)
    if mins < 180:
        return None
    return pid, passes / (mins / 90), {"apps": apps, "sub_out": sub_out,
                                       "avg_min": mins / apps if apps else 0, "pos": pos}


def _passes(stat_block):
    for s in stat_block["statistics"]:
        if s["type"] == "Total passes":
            return s["value"] or 0
    return None


def _red(stat_block):
    for st in stat_block["statistics"]:
        if st["type"] == "Red Cards":
            try:
                return int(st["value"] or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _form(tid):
    """Avg passes a team makes, passes opponents make against it, and the fixtures used.
    Games with a red card (either team) are left out when enough clean games remain, because
    a red card wrecks the pass counts. Costs no extra calls: red cards come with the same stats."""
    rows = []
    for f in _get("/fixtures", {"team": tid, "last": FORM_GAMES}):
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        blocks = _get("/fixtures/statistics", {"fixture": f["fixture"]["id"]})
        mine = [_passes(b) for b in blocks if b["team"]["id"] == tid]
        theirs = [_passes(b) for b in blocks if b["team"]["id"] != tid]
        if mine and theirs and mine[0] is not None and theirs[0] is not None:
            red = any(_red(b) > 0 for b in blocks)
            rows.append((f["fixture"]["id"], mine[0], theirs[0], red))
    clean = [r for r in rows if not r[3]]
    use = clean if len(clean) >= 3 else rows        # not enough clean games: fall back to all of them
    if len(use) < 3:
        return None
    return {"made": sum(r[1] for r in use) / len(use),
            "allowed": sum(r[2] for r in use) / len(use),
            "fids": [r[0] for r in use],
            "red_out": len(rows) - len(use),        # red-card games left out
            "red_in": any(r[3] for r in use)}       # red-card games still counted (too few clean games)


_fields_logged = {"done": False}


def _log_fields(blocks):
    """Once per run, print every stat field the API gives for a player in a game (shows if clearances/saves exist)."""
    if _fields_logged["done"]:
        return
    try:
        for team_block in blocks or []:
            for pl in team_block.get("players", []):
                st = (pl.get("statistics") or [None])[0]
                if st:
                    shape = {k: (sorted(v.keys()) if isinstance(v, dict) else type(v).__name__) for k, v in st.items()}
                    print("API player stat fields:", shape)
                    _fields_logged["done"] = True
                    return
    except Exception as e:
        print("could not log stat fields:", e)


def _last5(pid, fids):
    """The player's own passes in his team's last games (shared fixture lookups are cached per fixture)."""
    out = []
    for fid in fids:
        blocks = _cached(("fxp", fid), lambda fid=fid: _get("/fixtures/players", {"fixture": fid}))
        if blocks is None:
            raise RuntimeError("daily call cap or rate limit hit while reading last games")
        _log_fields(blocks)
        for team_block in blocks:
            for pl in team_block["players"]:
                if pl["player"]["id"] == pid:
                    st = pl["statistics"][0]
                    mins = st["games"]["minutes"] or 0
                    tot = st["passes"]["total"]
                    if mins >= 45 and tot is not None:
                        out.append(tot)
    return out


def _gk_vs(oid, fids):
    """Passes attempted by the goalkeepers who FACED this team in its recent games (other opponents, not just this one).
    Reuses the same per-fixture lookups the last-games check caches, so keepers on the same board share the calls."""
    out = []
    for fid in fids:
        blocks = _cached(("fxp", fid), lambda fid=fid: _get("/fixtures/players", {"fixture": fid}))
        if blocks is None:
            raise RuntimeError("daily call cap or rate limit hit while reading keeper games")
        _log_fields(blocks)
        for team_block in blocks:
            if (team_block.get("team") or {}).get("id") == oid:
                continue                                   # we want the OTHER side's keeper
            best = None
            for pl in team_block["players"]:
                st = pl["statistics"][0]
                if (st["games"].get("position") or "") != "G":
                    continue
                mins, tot = st["games"]["minutes"] or 0, (st.get("passes") or {}).get("total")
                if mins >= 60 and tot is not None and (best is None or mins > best[0]):
                    best = (mins, tot)
            if best:
                out.append(best[1])
    return out


def _h2h(pid, tid, oid):
    out, last = [], None
    fx = _get("/fixtures/headtohead", {"h2h": f"{tid}-{oid}", "last": H2H_GAMES})
    for f in fx:
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        for team_block in _get("/fixtures/players", {"fixture": f["fixture"]["id"]}):
            for pl in team_block["players"]:
                if pl["player"]["id"] == pid:
                    st = pl["statistics"][0]
                    mins = st["games"]["minutes"] or 0
                    tot = st["passes"]["total"]
                    if mins >= 30 and tot is not None:
                        out.append(round(tot / mins * 90, 1))
                        d = str(f["fixture"].get("date") or "")[:10]
                        if last is None or d >= last[0]:
                            last = (d, tot, mins)
    return {"per90": out, "last": last}


def calls_used():
    return _calls["n"]


def _err_text(e):
    e = str(e)
    if "Free plans" in e or "season locked" in e:
        return "free plan can't read this season (needs Pro)"
    if "cap" in e:
        return "daily call cap reached"
    if "429" in e:
        return "rate limit (too many calls per minute)"
    return e[:50]


def _why(*keys):
    for k in keys:
        e = _last_err.get(k)
        if e:
            return _err_text(e)
    return "not found"


def league_report():
    """One call at startup: which leagues have player + team passes for this season."""
    if not KEY or not MATCHUP:
        return ""
    try:
        data = _get("/leagues", {"season": SEASON})
    except Exception as e:
        return f"📋 League coverage check failed: {_err_text(e)}"
    idx = {}
    for it in data:
        idx[((it.get("country") or {}).get("name", "").lower(), it["league"]["name"].lower())] = it
    lines = []
    for item in LEAGUE_CHECK.split(","):
        if ":" not in item:
            continue
        country, lname = (x.strip() for x in item.split(":", 1))
        it = idx.get((country.lower(), lname.lower()))
        if not it:
            lines.append(f"❓ {country} – {lname}: not found")
            continue
        seasons = it.get("seasons") or []
        s = next((x for x in seasons if str(x.get("year")) == str(SEASON)), seasons[-1] if seasons else {})
        fx = (s.get("coverage") or {}).get("fixtures") or {}
        p, t = bool(fx.get("statistics_players")), bool(fx.get("statistics_fixtures"))
        icon = "✅" if (p and t) else ("🟡" if (p or t) else "❌")
        lines.append(f"{icon} {country} – {lname}"
                     + ("" if icon == "✅" else f" (player stats {'yes' if p else 'no'}, team stats {'yes' if t else 'no'})"))
    return (f"📋 Data coverage for {SEASON} (✅ = player + team passes available, not guaranteed every game)\n"
            + "\n".join(lines))


def lean_ex(name, team, opp, line):
    """Returns (note, juicy, reason). note is '' when stats are unavailable, and reason says why."""
    if not MATCHUP:
        return "", False, ""
    if not KEY:
        return "", False, "no API-Football key"
    if not team or not opp:
        return "", False, "PrizePicks gave no team/opponent"
    pk, tk, ok = ("player", name, team), ("team", team), ("team", opp)
    p = _cached(pk, lambda: _player(name, team))
    if not p:                                      # no player data -> don't spend calls on team lookups
        return "", False, "player: " + _why(pk)
    tid = _cached(tk, lambda: _team_id(team))
    oid = _cached(ok, lambda: _team_id(opp))
    if not (tid and oid):
        return "", False, "team: " + _why(tk, ok)
    pid, per90, risk = p
    fk1, fk2 = ("form", tid), ("form", oid)
    tf = _cached(fk1, lambda: _form(tid))
    of = _cached(fk2, lambda: _form(oid))
    if not (tf and of):
        return "", False, "recent games: " + _why(fk1, fk2)

    team_made, fids = tf["made"], tf["fids"]
    opp_allowed = of["allowed"]
    red_line = ""
    if tf["red_out"] or of["red_out"]:
        red_line = "\n   • Red-card games left out of the form numbers"
    elif tf["red_in"] or of["red_in"]:
        red_line = "\n   ⚠️ Form numbers include red-card games (too few clean ones)"
    expected_team = (team_made + opp_allowed) / 2
    factor = expected_team / team_made if team_made else 1
    proj = per90 * factor

    hd = _cached(("h2h", pid, oid), lambda: _h2h(pid, tid, oid)) or {"per90": [], "last": None}
    hh = hd["per90"]
    h2h_line = ""
    if len(hh) >= 2:
        proj = 0.5 * proj + 0.5 * (sum(hh) / len(hh))
        h2h_line = f"\n   • H2H: {', '.join(str(x) for x in hh)} ({len(hh)} games)"
    if hd["last"]:                                   # one previous meeting is shown, but only 2+ change the projection
        d, tot, mins = hd["last"]
        h2h_line += f"\n   • Last meeting: {tot} passes in {mins} min ({d})"

    is_gk = (risk.get("pos") or "").lower() == "goalkeeper"
    gkv, gk_vs_line = [], ""
    if is_gk:                                        # keepers: how many passes did keepers facing THIS team attempt lately?
        gkv = _cached(("gkvs", oid), lambda: _gk_vs(oid, of["fids"])) or []
        if len(gkv) >= 3:
            proj = 0.5 * proj + 0.5 * (sum(gkv) / len(gkv))
            gk_over = sum(1 for x in gkv if x > line)
            gk_vs_line = (f"\n   • Keepers facing {opp} lately: {', '.join(str(x) for x in gkv)}"
                          f" → over {line} in {gk_over}/{len(gkv)}")

    gap = proj - line
    juicy = abs(gap) >= max(EDGE_PCT * line, MIN_EDGE)
    if juicy:
        tag = "🔥 JUICY — lean OVER" if gap > 0 else "🧊 JUICY — lean UNDER"
    else:
        tag = "⚪ no clear edge"

    if juicy and MAX_GAP_RATIO and abs(gap) / max(line, 1) > MAX_GAP_RATIO:
        _suppressed["n"] += 1                       # a gap this big almost always means bad data, not a real edge
        return "", False, ""

    gk_line = ("\n   🧤 Goalkeeper: passes depend on his team's style and the flow of the game." if is_gk else "")
    gk_line += gk_vs_line

    last5_line = ""
    l5 = []
    if juicy or is_gk or LAST5_ALL:
        l5 = _cached(("last5", pid, tid), lambda: _last5(pid, fids)) or []
        if len(l5) >= 3:
            over = sum(1 for x in l5 if x > line)
            last5_line = (f"\n   • Last {len(l5)} games: {', '.join(str(x) for x in l5)}"
                          f" → over {line} in {over}/{len(l5)}"
                          + (" (red-card games left out)" if tf["red_out"] else ""))

    if juicy and RECENT_CHECK:
        lean_over = gap > 0
        disagree = False
        if len(l5) >= 3:                                   # most recent games must be on the lean side of the line
            hits = sum(1 for x in l5 if (x > line) == lean_over)
            disagree = hits / len(l5) < RECENT_AGREE
        if len(gkv) >= 4:                                  # keepers vs this opponent must lean the same way too
            gk_hits = sum(1 for x in gkv if (x > line) == lean_over)
            if gk_hits / len(gkv) < RECENT_AGREE:
                disagree = True
        lm = hd["last"]
        if lm and lm[2] >= 60 and (lm[1] > line) != lean_over:   # last full meeting went the other way
            disagree = True
        if disagree:
            _suppressed["n"] += 1
            return "", False, ""                           # post it as a plain passes line, no tag

    sub_line = ""
    if juicy and not is_gk and risk["apps"] >= SUB_MIN_APPS:
        rate = risk["sub_out"] / risk["apps"]
        if rate >= SUB_RATE or risk["avg_min"] < SUB_AVG_MIN:
            facts = f"subbed off in {risk['sub_out']} of {risk['apps']} apps, avg {risk['avg_min']:.0f} min"
            sub_line = (f"\n   ⚠️ Sub risk: {facts}. Passes can fall short." if gap > 0
                        else f"\n   ℹ️ Often subbed off ({facts}). That supports the under.")
    direction = ("OVER" if gap > 0 else "UNDER") if juicy else False
    return (f"\n   📊 Proj **{proj:.1f}** vs line {line} → {tag}"
            f"\n   • Avg {per90:.1f}/90 × {factor:.2f} matchup "
            f"(opp allows {opp_allowed:.0f}, their team makes {team_made:.0f})"
            f"{red_line}{gk_line}{h2h_line}{last5_line}{sub_line}", direction, "")


def lean(name, team, opp, line):
    note, juicy, _ = lean_ex(name, team, opp, line)
    return note, juicy


# ===== PRIZEPICKS MONITOR =====
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
INSTANCE = (os.getenv("RAILWAY_DEPLOYMENT_ID") or "not-railway")[:6]  # shows which copy posted
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}
session = requests.Session()
session.headers.update(HEADERS)

URL = "https://partner-api.prizepicks.com/projections?per_page=1000&single_stat=true&game_mode=pickem"


def fetch():
    r = session.get(URL, timeout=20)
    r.raise_for_status()
    return r.json()


def parse(data):
    players, leagues, games = {}, {}, {}
    for inc in data.get("included", []):
        a = inc.get("attributes", {})
        if inc.get("type") == "new_player":
            players[inc["id"]] = (a.get("name", "Unknown"),
                                  a.get("team") or a.get("team_name") or "")
        if inc.get("type") == "league":
            leagues[inc["id"]] = a.get("name", "")
        if inc.get("type") == "game":
            name = a.get("name") or a.get("description") or a.get("label") or "Soccer Match"
            games[inc["id"]] = {
                "name": name,
                "start": a.get("start_time") or a.get("game_time") or a.get("starts_at") or ""
            }

    cur = {}
    for item in data.get("data", []):
        try:
            attrs = item["attributes"]
            stat = str(attrs.get("stat_display_name", "")).lower()
            if "pass" not in stat or "attempt" not in stat:
                continue

            rel = item.get("relationships", {})
            league_id = rel.get("league", {}).get("data", {}).get("id")
            league_name = leagues.get(league_id, "").upper()
            if "NFL" in league_name or "CFB" in league_name or "NCAAF" in league_name or "FOOTBALL" in league_name:
                continue

            game_id = rel.get("game", {}).get("data", {}).get("id")
            game_info = games.get(game_id, {"name": league_name.title() or "Soccer Match", "start": ""})

            pid = rel.get("new_player", {}).get("data", {}).get("id")
            pname, pteam = players.get(pid, (attrs.get("description", "Unknown"), ""))

            opp = attrs.get("description", "")
            if pteam and opp:
                game_label = " vs ".join(sorted([pteam, opp]))
            else:
                game_label = game_info["name"]

            cur[item["id"]] = {
                "name": pname,
                "team": pteam,
                "opp": opp,   # PrizePicks puts the opponent here
                "line": attrs.get("line_score", 0),
                "league": league_name,
                "game_id": game_id,
                "game_name": game_label,
                "game_start": game_info["start"],
            }
        except Exception:
            continue
    return cur


def format_start_time(iso_str):
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%A, %B %d, %Y at %I:%M %p")
    except Exception:
        return iso_str


def _post(payload):
    """Post to Discord. If Discord says 'slow down' (429), wait the time it asks for and try again."""
    r = None
    for _ in range(4):
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code != 429:
            return r
        try:
            wait = float(r.json().get("retry_after", 2))
        except Exception:
            wait = 2.0
        print(f"Discord rate limit, retrying in {wait:.1f}s")
        time.sleep(min(wait, 15) + 0.5)
    return r


def _dir_prefix(direction):
    if direction == "OVER":
        return "🔥 **JUICY — LEAN OVER** — "
    if direction == "UNDER":
        return "🧊 **JUICY — LEAN UNDER** — "
    return ""


def send_grouped_embeds(props_to_send):
    if not WEBHOOK_URL or not props_to_send:
        return

    grouped = defaultdict(list)
    for info in props_to_send:
        grouped[(info["game_name"], info.get("juicy") or False)].append(info)   # over and under picks post separately

    for (game_name, direction), props in grouped.items():
        for p in props:
            try:
                _track(p)                     # v12: remember every tagged pick so the nightly recap can grade it
            except Exception as e:
                print("recap tracking failed:", e)
        start_str = format_start_time(props[0].get("game_start", ""))
        lines_text = "\n".join(
            [f"{_dir_prefix(p.get('juicy'))}{p['label']} — Passes `{p['line']}`{p['note']}" for p in props])

        if direction == "OVER":
            title, color = "🔥 Captain Hook — JUICY — LEAN OVER", 3066993
        elif direction == "UNDER":
            title, color = "🧊 Captain Hook — JUICY — LEAN UNDER", 10181046
        else:
            title, color = "🚨 Captain Hook — SOCCER PASSES", 3447003
        embed = {
            "title": title,
            "description": f"**{game_name}**\n{lines_text}",
            "color": color,
            "fields": [{"name": "Starts", "value": start_str, "inline": False}],
            "footer": {"text": f"PrizePicks • {len(props)} prop(s) • {INSTANCE}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _post({"username": "Captain Hook", "embeds": [embed]})


SWEEP_MINUTES = int(os.getenv("SWEEP_MINUTES", "120"))          # how often to re-check the WHOLE board
SWEEP_HOURS_AHEAD = float(os.getenv("SWEEP_HOURS_AHEAD", "30"))   # only games starting within this window
SWEEP_SUMMARY = os.getenv("SWEEP_SUMMARY", "true").lower() == "true"
SWEEP_CALL_BUDGET = int(os.getenv("SWEEP_CALL_BUDGET", "25"))     # max API calls one sweep may start (Pro: 1500)
SWEEP_KEEP = int(os.getenv("SWEEP_KEEP", "30"))                   # daily calls always kept for new/moved alerts (Pro: 300)
_judged = {"day": None, "keys": set()}


def _start_dt(info):
    try:
        return datetime.fromisoformat(info["game_start"].replace("Z", "+00:00"))
    except Exception:
        return None


def sweep(cur, already):
    """Check EVERY line on the board (soonest games first), not only new or moved ones."""
    if not MATCHUP:
        return
    now = datetime.now(timezone.utc)
    if _judged["day"] != now.date():
        _judged.update(day=now.date(), keys=set())
    rows = []
    for _id, info in cur.items():
        st = _start_dt(info)
        if st is not None and (st <= now or (st - now).total_seconds() > SWEEP_HOURS_AHEAD * 3600):
            continue
        rows.append((st or now + timedelta(days=9), _id, info))
    rows.sort(key=lambda r: r[0])

    checked = with_data = skipped = 0
    _suppressed["n"] = 0
    juicy_items, reasons = [], defaultdict(int)
    start_calls, stopped = calls_used(), False
    for _, _id, info in rows:
        k = (_id, info["line"])
        if k in _judged["keys"] or k in already:
            continue
        if calls_used() - start_calls >= SWEEP_CALL_BUDGET or CAP - calls_used() < SWEEP_KEEP:
            stopped = True
            skipped += 1
            continue
        note, juicy, reason = lean_ex(info["name"], info["team"], info["opp"], float(info["line"]))
        checked += 1
        if not note:
            if reason:
                reasons[reason] += 1
            continue
        with_data += 1
        _judged["keys"].add(k)
        if juicy:
            item = info.copy()
            item.update(note=note, juicy=juicy, label=f"🔎 {info['name']}")
            juicy_items.append(item)
            already.add(k)
    if juicy_items:
        send_grouped_embeds(juicy_items)
    print(f"Sweep: {len(rows)} lines in window, checked {checked}, with data {with_data}, juicy {len(juicy_items)}")
    if SWEEP_SUMMARY and WEBHOOK_URL:
        msg = (f"🔎 Board sweep: {len(rows)} lines in the next {SWEEP_HOURS_AHEAD:g}h • checked {checked} • "
               f"matchup data for {with_data} • juicy: {len(juicy_items)} "
               f"(🔥 {sum(1 for i in juicy_items if i['juicy'] == 'OVER')} over, "
               f"🧊 {sum(1 for i in juicy_items if i['juicy'] == 'UNDER')} under)")
        if reasons:
            top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
            msg += "\nNo matchup data for " + str(sum(reasons.values())) + ": " + ", ".join(f"{n}× {r}" for r, n in top)
        if _suppressed["n"]:
            msg += f"\n🔇 {_suppressed['n']} held back: projection looked unreliable or recent games disagreed"
        if stopped:
            msg += f"\n⏸️ Stopped early to protect today's calls: {skipped} lines left for the next sweep"
        msg += f"\nAPI-Football calls today: {calls_used()}/{CAP}"
        _post({"content": msg})



# ===== NIGHTLY RESULTS RECAP (v12) =====
# Remembers every 🔥/🧊 pick the bot posts. After the games finish it reads the final passes from API-Football,
# grades each pick (✅ cashed, ❌ missed, ➖ player did not play = void) and posts ONE recap per night.
RECAP = os.getenv("RECAP_ENABLED", "true").lower() == "true"
RECAP_TZ = os.getenv("RECAP_TZ", "America/New_York")                       # which clock decides what counts as "tonight"
RECAP_POST_HOUR = int(os.getenv("RECAP_POST_HOUR", "9"))                   # the recap posts at this hour (local) the NEXT morning; -1 = as soon as the games are done
RECAP_DAY_CUTOFF = int(os.getenv("RECAP_DAY_CUTOFF_HOUR", "6"))            # a game that kicks off before this hour counts as the previous night
RECAP_AFTER_MIN = int(os.getenv("RECAP_AFTER_MINUTES", "105"))             # start looking for a final score this long after kickoff
RECAP_EVERY_MIN = int(os.getenv("RECAP_CHECK_MINUTES", "15"))              # how often to check unfinished games
RECAP_MAX_WAIT_H = float(os.getenv("RECAP_MAX_WAIT_HOURS", "5"))           # post anyway this long after the last kickoff
RECAP_KEEP = int(os.getenv("RECAP_KEEP_CALLS", "15"))                      # never let the recap use the last N calls of the day
_ledger = {}
_recap = {"next": 0.0}
_fxs = {}                                                                  # (team id, date) -> (checked at, fixture)
_fxp_done = {}                                                             # fixture id -> player stats, kept once the game is final
FINAL = ("FT", "AET", "PEN")
DEAD = ("PST", "CANC", "ABD", "AWD", "WO")                                 # the match was not played: void
SYM = {"WIN": "✅", "LOSS": "❌", "VOID": "➖", "NODATA": "❔"}
# Running record shown at the bottom of every recap. It starts from these Railway variables and is saved to a small file,
# so a restart keeps it. A fresh deploy wipes the file: then it starts from the variables again, so keep them up to date.
RECORD_FILE = os.getenv("RECORD_FILE", "captain_hook_record.json")
_rec = {"w": 0, "l": 0, "v": 0}


def _load_record():
    base = {"w": int(os.getenv("RECORD_WINS", "0") or 0), "l": int(os.getenv("RECORD_LOSSES", "0") or 0),
            "v": int(os.getenv("RECORD_VOIDS", "0") or 0)}
    try:
        import json
        with open(RECORD_FILE) as fh:
            saved = json.load(fh)
        base = {k: int(saved.get(k, 0)) for k in ("w", "l", "v")}
    except Exception:
        pass                                                # no saved file yet: use the variables
    _rec.update(base)


def _save_record():
    try:
        import json
        with open(RECORD_FILE, "w") as fh:
            json.dump(_rec, fh)
    except Exception as e:
        print("could not save the record file:", e)


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(RECAP_TZ)
    except Exception:
        return timezone(timedelta(hours=-4))


def _local(dt):
    return dt.astimezone(_tz())


def _bday(dt):
    """The 'betting night' a kickoff belongs to: a 12:30 AM game still counts as the night before."""
    return (_local(dt) - timedelta(hours=RECAP_DAY_CUTOFF)).date()


def _utcnow():
    return datetime.now(timezone.utc)


def _track(info):
    if not RECAP or info.get("juicy") not in ("OVER", "UNDER"):
        return
    try:
        line = float(info["line"])
    except (TypeError, ValueError, KeyError):
        return
    key = (info["name"], info.get("game_name", ""), info["juicy"])
    e = _ledger.get(key)
    if e:
        if line not in e["lines"]:
            e["lines"].append(line)                         # the line moved and was posted again
        return
    team = info.get("team", "")
    ph, th = _cache.get(("player", info["name"], team)), _cache.get(("team", team))
    pv = ph[1] if ph else None
    _ledger[key] = {"name": info["name"], "team": team, "opp": info.get("opp", ""), "dir": info["juicy"],
                    "lines": [line], "game": info.get("game_name", ""),
                    "start": _start_dt(info) or datetime.now(timezone.utc),
                    "pid": pv[0] if pv else None, "tid": th[1] if th else None,
                    "pos": ((pv[2] or {}).get("pos") or "") if pv else "",
                    "state": "OPEN", "actual": None, "mins": None, "note": "", "recapped": False}


def _grade(line, actual, direction):
    if actual == line:
        return "VOID"                                       # a push
    return "WIN" if ((actual > line) == (direction == "OVER")) else "LOSS"


def _fixture_for(e):
    """The match this pick belongs to. Re-checked every few minutes until it is final."""
    date = e["start"].astimezone(timezone.utc).strftime("%Y-%m-%d")
    k = (e["tid"], date)
    hit = _fxs.get(k)
    if hit and (hit[1]["fixture"]["status"]["short"] in FINAL + DEAD or time.time() - hit[0] < RECAP_EVERY_MIN * 60 - 30):
        return hit[1]
    res = _get("/fixtures", {"team": e["tid"], "date": date})
    if not res:
        return None
    pick = res[0]
    if len(res) > 1:
        for f in res:
            names = [f["teams"]["home"]["name"], f["teams"]["away"]["name"]]
            if any(_team_like(e["opp"], n) for n in names):
                pick = f
                break
    _fxs[k] = (time.time(), pick)
    return pick


def _settle_one(e, now):
    if now < e["start"] + timedelta(minutes=RECAP_AFTER_MIN):
        return                                              # the game is still on, or just ended
    if e["pid"] is None or e["tid"] is None:
        if now > e["start"] + timedelta(hours=RECAP_MAX_WAIT_H):
            e["state"], e["note"] = "NODATA", "could not match the player or team"
        return
    f = _fixture_for(e)
    if not f:
        return
    st = f["fixture"]["status"]["short"]
    if st in DEAD:
        e["state"], e["note"] = "VOID", "match postponed or cancelled"
        return
    if st not in FINAL:
        return                                              # still being played
    fid = f["fixture"]["id"]
    blocks = _fxp_done.get(fid)
    if blocks is None:
        blocks = _get("/fixtures/players", {"fixture": fid})
        if not blocks:
            return                                          # stats are not out yet, try again next round
        _fxp_done[fid] = blocks
    found = None
    for tb in blocks:
        for pl in tb.get("players", []):
            if pl["player"]["id"] == e["pid"]:
                found = pl["statistics"][0]
    mins = ((found or {}).get("games") or {}).get("minutes") or 0
    tot = ((found or {}).get("passes") or {}).get("total")
    if found and mins > 0 and tot is not None:
        e["actual"], e["mins"] = tot, mins
        e["state"] = _grade(e["lines"][0], tot, e["dir"])
        return
    if found and mins > 0:
        e["state"], e["note"] = "NODATA", "no pass stats for him"
        return
    e["state"], e["note"] = "VOID", ("did not play" if found else "not in the match stats")
    if (e["pos"] or "").lower() == "goalkeeper":            # a keeper who did not start: show who played instead
        best = None
        for tb in blocks:
            if (tb.get("team") or {}).get("id") != e["tid"]:
                continue
            for pl in tb.get("players", []):
                s0 = pl["statistics"][0]
                m2, t2 = (s0["games"].get("minutes") or 0), (s0.get("passes") or {}).get("total")
                if (s0["games"].get("position") or "") == "G" and m2 > 0 and t2 is not None and (best is None or m2 > best[0]):
                    best = (m2, t2, pl["player"].get("name", "?"))
        if best:
            e["note"] += f"; keeper who played: {best[2]} {best[1]} passes ({_grade(e['lines'][0], best[1], e['dir'])})"
            e["shadow"] = _grade(e["lines"][0], best[1], e["dir"])


def _entry_line(e):
    sym = SYM.get(e["state"], "⏳")
    txt = f"**{e['name']}** — {e['dir']} {e['lines'][0]:g} {sym}"
    if e["state"] in ("WIN", "LOSS"):
        txt += f" ({e['actual']} passes, {e['mins']}')"
        for L in e["lines"][1:]:                           # picks that were posted again at a moved line
            txt += f" · also at {L:g} {SYM[_grade(L, e['actual'], e['dir'])]}"
    elif e["note"]:
        txt += f" · {e['note']}"
    return txt


def _post_recap(date_label, members):
    done = [e for e in members if e["state"] in ("WIN", "LOSS")]
    w = sum(1 for e in done if e["state"] == "WIN")
    l = len(done) - w
    v = sum(1 for e in members if e["state"] == "VOID")
    u = sum(1 for e in members if e["state"] == "NODATA")
    lines = [_entry_line(e) for e in members]
    _rec["w"] += w
    _rec["l"] += l
    _rec["v"] += v
    _save_record()
    tw, tl = _rec["w"], _rec["l"]
    foot = (f"\n\nTonight: **{w}-{l}**" + (f" (+{v} void)" if v else "") + (f" (+{u} not graded)" if u else "")
            + f"\n**Record: {tw}-{tl}**" + (f" ({round(100 * tw / (tw + tl))}%)" if (tw + tl) else ""))
    embed = {"title": f"📋 Captain Hook — results — {date_label}", "description": ("\n".join(lines) + foot)[:4000],
             "color": 15844367, "footer": {"text": "Graded on passes attempted • ➖ = did not play (void) • " + INSTANCE},
             "timestamp": datetime.now(timezone.utc).isoformat()}
    _post({"username": "Captain Hook", "embeds": [embed]})
    for e in members:
        e["recapped"] = True
    print(f"Recap posted for {date_label}: {w}-{l}-{v}, running record {_rec['w']}-{_rec['l']}-{_rec['v']}")


def settle_and_recap():
    if not RECAP or not _ledger or not WEBHOOK_URL:
        return
    now = _utcnow()
    if CAP - calls_used() >= RECAP_KEEP:
        for e in _ledger.values():
            if e["state"] == "OPEN":
                try:
                    _settle_one(e, now)
                except Exception as ex:
                    print("recap settle failed:", e["name"], ex)
                    if "cap" in str(ex) or "429" in str(ex):
                        break
    groups = defaultdict(list)
    for e in _ledger.values():
        if not e["recapped"]:
            groups[_bday(e["start"])].append(e)
    for d, members in sorted(groups.items()):
        if RECAP_POST_HOUR >= 0:                            # wait for the morning after: late games (MLS) finish after midnight
            post_at = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=_tz()) + timedelta(hours=RECAP_POST_HOUR)
            if now < post_at:
                continue
        if any(e["state"] == "OPEN" for e in members):
            if now < max(e["start"] for e in members) + timedelta(hours=RECAP_MAX_WAIT_H):
                continue                                    # still waiting on a game
            for e in members:
                if e["state"] == "OPEN":
                    e["state"], e["note"] = "NODATA", "no final stats yet"
        members.sort(key=lambda e: e["start"])
        _post_recap(d.strftime("%a %b %d").replace(" 0", " "), members)


def main():
    print(f"Captain Hook - SOCCER Passes Attempted - MATCHUP {'MODE' if MATCHUP else 'OFF'} - instance {INSTANCE}")
    _load_record()
    print(f"Running record starts at {_rec['w']}-{_rec['l']}-{_rec['v']} (wins-losses-voids)")

    seen = None
    while seen is None:
        try:
            seen = parse(fetch())
        except Exception as e:
            print(f"Initial fetch failed: {e}")
            time.sleep(60)
    print(f"Initial tracking {len(seen)} SOCCER passes lines")
    if WEBHOOK_URL:
        extra = f"\n{status()}" if MATCHUP else "\nMatchup lookups are OFF (line alerts only)."
        r = _post({
            "content": f"✅ Captain Hook live: tracking {len(seen)} soccer Passes lines. "
                       f"All new lines and bumps post. Juicy matchups: 🔥 = lean OVER, 🧊 = lean UNDER. "
                       f"A results recap posts after the games finish.{extra}"})
        print(f"Startup message -> Discord status {r.status_code}")
        print(status())
        if LEAGUE_CHECK_ON_START and MATCHUP:
            try:
                rep = league_report()
                if rep:
                    _post({"content": rep[:1900]})
            except Exception as e:
                print(f"League report failed: {e}")
    else:
        print("WEBHOOK_URL is not set")

    alerted, next_sweep = set(), time.time() + 90
    while True:
        time.sleep(60)
        try:
            cur = parse(fetch())
            to_send = []
            for _id, info in cur.items():
                is_new = _id not in seen
                moved = (not is_new) and info["line"] != seen[_id]["line"]
                if not (is_new or moved):
                    continue

                note, juicy, why = lean_ex(info["name"], info["team"], info["opp"], float(info["line"]))
                if not note and why:
                    note = f"\n   ℹ️ No matchup data: {why}"

                item = info.copy()
                item["note"] = note
                item["juicy"] = juicy
                if juicy:
                    alerted.add((_id, info["line"]))
                item["label"] = (f"📈 {info['name']} {seen[_id]['line']} -> {info['line']}"
                                 if moved else info["name"])
                to_send.append(item)

            if to_send:
                send_grouped_embeds(to_send)

            seen = cur
            print(f"Checked {len(cur)} soccer lines, sent {len(to_send)}")
            if time.time() >= next_sweep:
                next_sweep = time.time() + SWEEP_MINUTES * 60
                try:
                    sweep(cur, alerted)
                except Exception as e:
                    print(f"Sweep failed: {e}")
            if RECAP and time.time() >= _recap["next"]:
                _recap["next"] = time.time() + RECAP_EVERY_MIN * 60
                try:
                    settle_and_recap()
                except Exception as e:
                    print(f"Recap failed: {e}")
        except Exception as e:
            print(f"Error {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()

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


def _player(name):
    if _season_locked():
        raise RuntimeError("free plan: season locked")      # don't spend a call on a lookup that will be blocked
    parts = _clean(name).split()
    if not parts or len(parts[-1]) < 3:
        return None
    one_name = len(parts) == 1                    # Rodri, Pedri, most Brazilians
    first, last = parts[0].lower(), parts[-1].lower()
    cands = _get("/players/profiles", {"search": last})
    pid = None
    for p in cands:
        pl = p["player"]
        fn = _clean(pl.get("firstname") or "").lower()
        ln = _clean(pl.get("lastname") or "").lower()
        nm = _clean(pl.get("name") or "").lower()
        ln_tail = ln.split()[-1] if ln else ""    # "De Bruyne" -> "bruyne", "van Dijk" -> "dijk"
        nm_tail = nm.split()[-1] if nm else ""
        if one_name:
            ok = last in (fn, ln, nm)
        else:
            ok = ((ln == last or ln_tail == last) and fn[:1] == first[:1]) or \
                 (nm_tail == last and nm[:1] == first[:1])
        if ok:
            pid = pl["id"]
            print("player matched:", name, "->", pl.get("firstname"), pl.get("lastname"), "id", pid)
            break
    if not pid:
        print("player not matched:", name, [(c["player"].get("firstname"), c["player"].get("lastname"),
                                              c["player"].get("name")) for c in cands][:8])
        return None
    data = _get("/players", {"id": pid, "season": SEASON})
    passes = mins = apps = sub_out = 0
    pos = ""
    for s in (data[0]["statistics"] if data else []):
        passes += s["passes"]["total"] or 0
        mins += s["games"]["minutes"] or 0
        apps += s["games"].get("appearences") or 0
        sub_out += (s.get("substitutes") or {}).get("out") or 0
        pos = pos or (s["games"].get("position") or "")
    if mins < 180:
        return None
    return pid, passes / (mins / 90), {"apps": apps, "sub_out": sub_out,
                                       "avg_min": mins / apps if apps else 0, "pos": pos}


def _passes(stat_block):
    for s in stat_block["statistics"]:
        if s["type"] == "Total passes":
            return s["value"] or 0
    return None


def _form(tid):
    """Avg passes a team makes, passes opponents make against it (last 5), and the fixture ids used."""
    made, allowed, fids = [], [], []
    for f in _get("/fixtures", {"team": tid, "last": 5}):
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        blocks = _get("/fixtures/statistics", {"fixture": f["fixture"]["id"]})
        mine = [_passes(b) for b in blocks if b["team"]["id"] == tid]
        theirs = [_passes(b) for b in blocks if b["team"]["id"] != tid]
        if mine and theirs and mine[0] is not None and theirs[0] is not None:
            made.append(mine[0])
            allowed.append(theirs[0])
            fids.append(f["fixture"]["id"])
    if len(made) < 3:
        return None
    return sum(made) / len(made), sum(allowed) / len(allowed), fids


def _last5(pid, fids):
    """The player's own passes in his team's last games (shared fixture lookups are cached per fixture)."""
    out = []
    for fid in fids:
        blocks = _cached(("fxp", fid), lambda fid=fid: _get("/fixtures/players", {"fixture": fid}))
        if blocks is None:
            raise RuntimeError("daily call cap or rate limit hit while reading last games")
        for team_block in blocks:
            for pl in team_block["players"]:
                if pl["player"]["id"] == pid:
                    st = pl["statistics"][0]
                    mins = st["games"]["minutes"] or 0
                    tot = st["passes"]["total"]
                    if mins >= 45 and tot is not None:
                        out.append(tot)
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
    pk, tk, ok = ("player", name), ("team", team), ("team", opp)
    p = _cached(pk, lambda: _player(name))
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

    team_made, _, fids = tf
    _, opp_allowed, _ = of
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

    gap = proj - line
    juicy = abs(gap) >= max(EDGE_PCT * line, MIN_EDGE)
    if juicy:
        tag = "🔥 JUICY — lean OVER" if gap > 0 else "🧊 JUICY — lean UNDER"
    else:
        tag = "⚪ no clear edge"

    is_gk = (risk.get("pos") or "").lower() == "goalkeeper"
    gk_line = "\n   🧤 Goalkeeper: passes depend on his team's style and the flow of the game." if is_gk else ""

    last5_line = ""
    if juicy or is_gk or LAST5_ALL:
        l5 = _cached(("last5", pid, tid), lambda: _last5(pid, fids)) or []
        if len(l5) >= 3:
            over = sum(1 for x in l5 if x > line)
            last5_line = (f"\n   • Last {len(l5)} games: {', '.join(str(x) for x in l5)}"
                          f" → over {line} in {over}/{len(l5)}")

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
            f"{gk_line}{h2h_line}{last5_line}{sub_line}", direction, "")


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
        if stopped:
            msg += f"\n⏸️ Stopped early to protect today's calls: {skipped} lines left for the next sweep"
        msg += f"\nAPI-Football calls today: {calls_used()}/{CAP}"
        _post({"content": msg})


def main():
    print(f"Captain Hook - SOCCER Passes Attempted - MATCHUP {'MODE' if MATCHUP else 'OFF'} - instance {INSTANCE}")

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
                       f"All new lines and bumps post. Juicy matchups: 🔥 = lean OVER, 🧊 = lean UNDER.{extra}"})
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
        except Exception as e:
            print(f"Error {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()

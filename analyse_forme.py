"""Quel poids donner à la forme récente ? Test sur les Gamedays déjà joués.

Pour chaque match joué (minutes > 0), on refait la projection telle qu'elle aurait été calculée la veille,
avec seulement les matchs précédents : projection d'avant-saison (priors.json), moyenne de la saison
(K matchs fictifs pour l'avant-saison) puis forme récente (moyenne des n derniers matchs, poids w, à partir
de 5 matchs). On compare ensuite à ses vrais points, pour plusieurs réglages (K, w, n).

    python3 analyse_forme.py
"""
import json, statistics as st, urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
API = "https://nbafantasy.nba.com/api/"
UA = {"User-Agent": "Mozilla/5.0 (assistant-nba-fantasy perso)"}


def get(chemin):
    with urllib.request.urlopen(urllib.request.Request(API + chemin, headers=UA), timeout=30) as r:
        return json.load(r)


def main():
    boot = get("bootstrap-static/")
    el = {e["id"]: e for e in boot["elements"]}
    priors = json.loads((ICI / "priors.json").read_text(encoding="utf-8"))["joueurs"]
    cfg = json.loads((ICI / "config.json").read_text(encoding="utf-8"))
    finis = [e for e in boot["events"] if e.get("finished") or e.get("data_checked")]
    matchs = {}   # pid → [(event, pts, minutes)] dans l'ordre
    for e in finis:
        for x in get(f"event/{e['id']}/live/")["elements"]:
            s = x["stats"]
            if s.get("minutes", 0) > 0:
                matchs.setdefault(x["id"], []).append((e["id"], s.get("total_points", 0) / 10, s["minutes"]))
    print(f"{len(finis)} Gamedays terminés, {sum(len(v) for v in matchs.values())} matchs joués")
    prior = lambda pid: priors.get(str(pid), {}).get("fppg", 2.59 * el[pid]["now_cost"] / 10 + 1.4)

    def projection(pid, avant, K, w, n):
        base = prior(pid)
        g = len(avant)
        if g:
            ppg = sum(p for _, p, _ in avant) / g
            base = g / (g + K) * ppg + K / (g + K) * base
            if g >= 5 and w:
                forme = sum(p for _, p, _ in avant[-n:]) / len(avant[-n:])
                base = (1 - w) * base + w * forme
        return base

    reglages = [(K, w, n) for K in (1.5, 3, 6) for w in (0, 0.25, 0.4, 0.55, 0.7, 1.0) for n in (3, 5)]
    groupes = {"tous (projetés ≥ 20)": lambda pid, pr: pr >= 20, "≥ 15 M$": lambda pid, pr: el[pid]["now_cost"] >= 150,
               "10-15 M$": lambda pid, pr: 100 <= el[pid]["now_cost"] < 150, "< 10 M$ (projetés ≥ 20)": lambda pid, pr: el[pid]["now_cost"] < 100 and pr >= 20}
    res = {}
    for K, w, n in reglages:
        par = {g: [] for g in groupes}
        for pid, lst in matchs.items():
            if pid not in el:
                continue
            for i in range(5, len(lst)):   # seulement les matchs où la forme peut jouer (5 matchs avant)
                pr = projection(pid, lst[:i], K, w, n)
                for g, f in groupes.items():
                    if f(pid, pr):
                        par[g].append((pr, lst[i][1]))
        res[(K, w, n)] = par
    actuel = (cfg.get("poids_points_avant_saison", 8), cfg.get("poids_forme", 0.25), 5)
    print(f"Réglage actuel : K = {actuel[0]}, poids de la forme = {actuel[1]}, forme sur {actuel[2]} matchs\n")
    for g in groupes:
        lignes = []
        for r, par in res.items():
            v = par[g]
            if len(v) < 20:
                continue
            mae = st.mean(abs(b - a) for a, b in v)
            biais = st.mean(b - a for a, b in v)
            lignes.append((mae, biais, r, len(v)))
        lignes.sort()
        print(f"== {g} ({lignes[0][3] if lignes else 0} matchs) — erreur moyenne (pts), biais réel − projeté")
        for mae, biais, (K, w, n), _ in lignes[:6]:
            print(f"   K={K:<4} forme {w:.2f} sur {n} matchs : erreur {mae:5.2f} | biais {biais:+5.2f}")
        ref = next(((m, b) for m, b, r, _ in lignes if r == (actuel[0], actuel[1], 5)), None)
        if ref:
            print(f"   (réglage actuel : erreur {ref[0]:5.2f} | biais {ref[1]:+5.2f})")
        print()
    # Le cas Doncic, pour illustrer
    for pid in (257,):
        lst = matchs.get(pid, [])
        print(f"{el[pid]['web_name']} : derniers matchs {[p for _, p, _ in lst[-6:]]} | projection actuelle "
              f"{projection(pid, lst, *actuel):.1f} | avec le meilleur réglage global "
              f"{projection(pid, lst, *min(res, key=lambda r: st.mean(abs(b - a) for a, b in res[r]['tous (projetés ≥ 20)']) if res[r]['tous (projetés ≥ 20)'] else 99)):.1f}")


if __name__ == "__main__":
    main()

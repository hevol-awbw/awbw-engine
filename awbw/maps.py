"""Map loading. AWBW maps are grids of numeric terrain ids (see terrain_map.php)."""
from __future__ import annotations

from .data import TERRAIN_IDS, TK
from .game import Game


def parse_awbw_csv(text: str, countries=(1, 2)):
    """Parse rows of comma-separated AWBW terrain ids -> (kinds, owners) for a 1v1 game.

    `countries` = (country id of player 0, country id of player 1). Properties of any other
    country become neutral; an HQ belonging to a non-participating country becomes a city.
    """
    kinds, owners = [], []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        krow, orow = [], []
        for tok in line.replace(" ", "").split(","):
            if tok == "":
                continue
            tid = int(tok)
            if tid not in TERRAIN_IDS:
                raise ValueError(f"unsupported terrain id {tid}")
            tk, cid = TERRAIN_IDS[tid]
            if cid in countries:
                owner = countries.index(cid)
            else:
                owner = -1
                if tk == TK.HQ:
                    tk = TK.CITY
            krow.append(tk)
            orow.append(owner)
        kinds.append(krow)
        owners.append(orow)
    if len({len(r) for r in kinds}) != 1:
        raise ValueError("ragged map")
    return kinds, owners


_LEGEND = {
    ".": (TK.PLAIN, -1), "^": (TK.MOUNTAIN, -1), "@": (TK.WOOD, -1), "r": (TK.RIVER, -1),
    "=": (TK.ROAD, -1), "~": (TK.SEA, -1), "s": (TK.SHOAL, -1), "%": (TK.REEF, -1),
    "c": (TK.CITY, -1), "C": (TK.CITY, 0), "D": (TK.CITY, 1),
    "n": (TK.BASE, -1), "B": (TK.BASE, 0), "b": (TK.BASE, 1),
    "H": (TK.HQ, 0), "h": (TK.HQ, 1),
    "A": (TK.AIRPORT, 0), "a": (TK.AIRPORT, 1), "P": (TK.PORT, 0), "p": (TK.PORT, 1),
    "S": (TK.SILO, -1), "T": (TK.COMTOWER, -1), "t": (TK.COMTOWER, 0), "L": (TK.LAB, -1),
}


def from_ascii(rows):
    kinds, owners = [], []
    for row in rows:
        kinds.append([_LEGEND[ch][0] for ch in row])
        owners.append([_LEGEND[ch][1] for ch in row])
    return kinds, owners


def make_game(rows, units=(), **kw) -> Game:
    """Build a Game from an ASCII map. units = [(player, UT, x, y[, hp])]."""
    kinds, owners = from_ascii(rows)
    return Game(kinds, owners, units=units, **kw)

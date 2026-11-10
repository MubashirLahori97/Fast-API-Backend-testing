"""Which state a ZIP code belongs to (stories 1.1 and 11.1: "Please enter a valid state and ZIP
code.").

Every US ZIP code has five digits, in every state. The first three (the prefix) are assigned by
the USPS to one state, so a ZIP code belongs to the state that has its prefix. New ZIP codes
keep their area's prefix, so this table doesn't go out of date the way a list of every ZIP code
would. A typo that lands on an unused prefix next to the state's own still passes; that's the
trade-off for never turning away a real one.

Source: the USPS 3-digit prefix assignments, cross-checked on 6 Nov 2026 against the lowest and
highest ZIP code per state on https://www.structnet.com/instructions/zip_min_max_by_state.html
and the cross-state examples in Wikipedia's "ZIP Code" article (739 is Oklahoma, 297 South
Carolina, 865 Arizona and 961 California, although each is sorted in a neighbouring state).
Ranges are inclusive and include unused prefixes inside a state's range.
"""

# The 50 states and DC: the 3-digit prefixes each one has.
_PREFIXES: dict[str, str] = {
    "AL": "350-369",
    "AK": "995-999",
    "AZ": "850-865",
    "AR": "716-729",
    "CA": "900-961",
    "CO": "800-816",
    "CT": "060-069",
    "DE": "197-199",
    "DC": "200 202-205 569",
    "FL": "320-349",
    "GA": "300-319 398-399",
    "HI": "967-968",
    "ID": "832-838",
    "IL": "600-629",
    "IN": "460-479",
    "IA": "500-528",
    "KS": "660-679",
    "KY": "400-427",
    "LA": "700-714",
    "ME": "039-049",
    "MD": "206-219",
    "MA": "010-027 055",
    "MI": "480-499",
    "MN": "550-567",
    "MS": "386-397",
    "MO": "630-658",
    "MT": "590-599",
    "NE": "680-693",
    "NV": "889-898",
    "NH": "030-038",
    "NJ": "070-089",
    "NM": "870-884",
    "NY": "005 100-149",
    "NC": "270-289",
    "ND": "580-588",
    "OH": "430-459",
    "OK": "730-732 734-749",
    "OR": "970-979",
    "PA": "150-196",
    "RI": "028-029",
    "SC": "290-299",
    "SD": "570-577",
    "TN": "370-385",
    "TX": "733 750-799 885",
    "UT": "840-847",
    "VT": "050-054 056-059",
    "VA": "201 220-246",
    "WA": "980-994",
    "WV": "247-268",
    "WI": "530-549",
    "WY": "820-831",
}

# ZIP codes in one state that use a neighbouring state's prefix.
_EXCEPTIONS: dict[str, frozenset[str]] = {
    "NY": frozenset({"06390"}),  # Fishers Island, on Connecticut's 063
    "AR": frozenset({"75502"}),  # Texarkana, Arkansas, on Texas's 755
    "MS": frozenset({"71233"}),  # Warren County, on Louisiana's 712
    "DC": frozenset({"20799"}),  # a federal ZIP code on Maryland's 207
    "WY": frozenset({"83414"}),  # Alta, Wyoming, on Idaho's 834
}


def _ranges(spec: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    for part in spec.split():
        low, _, high = part.partition("-")
        ranges.append((int(low), int(high or low)))
    return tuple(ranges)


PREFIXES: dict[str, tuple[tuple[int, int], ...]] = {
    state: _ranges(spec) for state, spec in _PREFIXES.items()
}


def zip_in_state(zip_code: str, state: str) -> bool:
    """Whether a valid ZIP code ("12345" or "12345-6789") belongs to the state (a USPS code
    such as "HI")."""
    five = zip_code[:5]
    if five in _EXCEPTIONS.get(state, frozenset()):
        return True
    prefix = int(five[:3])
    return any(low <= prefix <= high for low, high in PREFIXES.get(state, ()))

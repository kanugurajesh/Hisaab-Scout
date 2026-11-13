"""Offline GSTIN checks. No network, no scraping: the number itself carries a lot.

A GSTIN is 15 characters:
  27      AAPFU0939F   1         Z        V
  state   PAN          entity #  default  check digit
The last character is a mod-36 check digit over the first 14, so most made-up or mistyped numbers
fail it. The 4th PAN letter says what kind of entity holds it (P = individual, C = company, ...).
"""

import re
from dataclasses import dataclass

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu (old code)", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (old code)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

ENTITY_TYPES = {
    "P": "Individual (proprietor)", "C": "Company", "F": "Firm or LLP", "H": "Hindu Undivided Family",
    "A": "Association of Persons", "B": "Body of Individuals", "T": "Trust", "L": "Local authority",
    "J": "Artificial juridical person", "G": "Government",
}

# Characters OCR and people confuse. Position tells which one is right (digit slot or letter slot).
DIGIT_SLOTS = {0, 1, 7, 8, 9, 10}
LETTER_SLOTS = {2, 3, 4, 5, 6, 11}
TO_DIGIT = {"O": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}
TO_LETTER = {v: k for k, v in TO_DIGIT.items() if k not in ("D", "L", "G", "T")} | {"0": "O"}
SWAPS = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2"}


def normalize(raw: str) -> str:
    return re.sub(r"[\s\-./]", "", raw or "").upper()


def check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARS[(36 - total % 36) % 36]


def checksum_ok(gstin: str) -> bool:
    return len(gstin) == 15 and all(c in CHARS for c in gstin) and check_digit(gstin[:14]) == gstin[14]


def format_ok(gstin: str) -> bool:
    return PATTERN.match(gstin) is not None


def suggest_fix(gstin: str) -> str | None:
    """If the number fails, is there exactly one likely misreading (O for 0, I for 1, ...) that makes it
    valid? Only ever offered as a suggestion: the organizer compares it with the bill."""
    if len(gstin) != 15 or (format_ok(gstin) and checksum_ok(gstin)):
        return None
    # Step 1: put digits in digit slots and letters in letter slots.
    fixed = list(gstin)
    for i, ch in enumerate(fixed):
        if i in DIGIT_SLOTS and ch in TO_DIGIT:
            fixed[i] = TO_DIGIT[ch]
        elif i in LETTER_SLOTS and ch in TO_LETTER:
            fixed[i] = TO_LETTER[ch]
    if fixed[13] == "2":
        fixed[13] = "Z"
    base = "".join(fixed)
    if format_ok(base) and checksum_ok(base):
        return base
    # Step 2: one confusable swap in the slots that can hold either (entity number, check digit).
    found = set()
    for i in (12, 14):
        if base[i] in SWAPS:
            cand = base[:i] + SWAPS[base[i]] + base[i + 1:]
            if format_ok(cand) and checksum_ok(cand):
                found.add(cand)
    return found.pop() if len(found) == 1 else None


@dataclass(frozen=True)
class GstinFacts:
    gstin: str
    format_ok: bool
    checksum_ok: bool
    state: str | None
    entity_type: str | None
    pan: str | None
    suggestion: str | None


def inspect(raw: str) -> GstinFacts:
    g = normalize(raw)
    fmt = format_ok(g)
    return GstinFacts(
        gstin=g,
        format_ok=fmt,
        checksum_ok=checksum_ok(g),
        state=STATES.get(g[:2]) if len(g) >= 2 else None,
        entity_type=ENTITY_TYPES.get(g[5]) if fmt else None,
        pan=g[2:12] if fmt else None,
        suggestion=suggest_fix(g),
    )

"""Template fingerprint (FAZA 3) — SimHash over normalized NEW content.

Used to scope decarantine-learning to mail NEAR-IDENTICAL to what a human approved,
instead of releasing ANY mail from a sender. Pure stdlib (hashlib/re), no DB or config.

  fp = fingerprint(text)            # -> 64-bit int (or None if too little content)
  d  = hamming(fp_a, fp_b)          # -> 0..64 bits differing
  matches(fp_a, fp_b, k=3)          # -> True if same template (Hamming <= k)

Normalization deliberately strips the parts that vary between instances of the same
template (digits: ticket ids / dates / amounts; URLs; punctuation; whitespace) so two
renderings of one template collapse to the same/near fingerprint, while genuinely
different mail diverges.
"""
import re
import hashlib
from typing import Optional

BITS = 64
_URL = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_NONWORD = re.compile(r'[^a-z0-9\s]+')
_DIGIT = re.compile(r'\d+')
_WS = re.compile(r'\s+')
MIN_TOKENS = 5  # below this the fingerprint is not discriminative -> return None


def _normalize(text: str) -> str:
    s = (text or '').lower()
    s = _URL.sub(' ', s)
    s = _NONWORD.sub(' ', s)
    s = _DIGIT.sub(' ', s)      # drop varying numbers (ticket/date/amount)
    s = _WS.sub(' ', s).strip()
    return s


def _shingles(norm: str):
    toks = [t for t in norm.split(' ') if len(t) >= 2]
    if len(toks) < MIN_TOKENS:
        return None
    grams = list(toks)                                   # unigrams
    grams += [toks[i] + ' ' + toks[i + 1] for i in range(len(toks) - 1)]  # bigrams
    return grams


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode('utf-8'), digest_size=8).digest(), 'big')


def fingerprint(text: str) -> Optional[int]:
    norm = _normalize(text)
    grams = _shingles(norm)
    if not grams:
        return None
    v = [0] * BITS
    for g in grams:
        h = _hash64(g)
        for b in range(BITS):
            v[b] += 1 if (h >> b) & 1 else -1
    fp = 0
    for b in range(BITS):
        if v[b] > 0:
            fp |= (1 << b)
    return fp


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << BITS) - 1)).count('1')


def matches(a: Optional[int], b: Optional[int], k: int = 3) -> bool:
    if a is None or b is None:
        return False
    return hamming(a, b) <= k

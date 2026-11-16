"""Twelve small Python coding tasks used by the Relaypack benchmark.

Each task has a spec (what the agents see), hidden tests (only the Tester runs
them), a reference solution, a typical first-attempt bug, and the pitfall
category that bug belongs to. Pitfall categories repeat across tasks on
purpose: a lesson learned on task 1 is useful again on task 11, which is what
shared memory should exploit.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    id: str
    func: str
    spec: str
    tests: list[str] = field(default_factory=list)
    solution: str = ""
    buggy: str = ""
    pitfall: str = ""  # "empty" | "case" | "negative" | ""


LESSONS = {
    "empty": "Handle empty input explicitly: return the documented default instead of raising (no max()/min()/division/indexing on an empty sequence).",
    "case": "Normalize letter case (str.lower()) before comparing or counting text.",
    "negative": "Handle negative numbers: never assume str(n) contains only digits; work on abs(n) and re-apply the sign.",
}


TASKS: list[Task] = [
    Task("t01", "mean", "mean(xs: list[float]) -> float. Arithmetic mean of xs. Return 0.0 for an empty list.",
         ["assert mean([1, 2, 3]) == 2", "assert mean([]) == 0.0", "assert mean([5]) == 5"],
         "def mean(xs):\n    if not xs:\n        return 0.0\n    return sum(xs) / len(xs)\n",
         "def mean(xs):\n    return sum(xs) / len(xs)\n", "empty"),
    Task("t02", "word_freq", "word_freq(text: str) -> dict[str, int]. Count words split on whitespace, case-insensitive (keys lowercase).",
         ["assert word_freq('a A b') == {'a': 2, 'b': 1}", "assert word_freq('') == {}"],
         "def word_freq(text):\n    out = {}\n    for w in text.lower().split():\n        out[w] = out.get(w, 0) + 1\n    return out\n",
         "def word_freq(text):\n    out = {}\n    for w in text.split():\n        out[w] = out.get(w, 0) + 1\n    return out\n", "case"),
    Task("t03", "digit_sum", "digit_sum(n: int) -> int. Sum of the decimal digits of n; the sign is ignored.",
         ["assert digit_sum(123) == 6", "assert digit_sum(-45) == 9", "assert digit_sum(0) == 0"],
         "def digit_sum(n):\n    return sum(int(c) for c in str(abs(n)))\n",
         "def digit_sum(n):\n    return sum(int(c) for c in str(n))\n", "negative"),
    Task("t04", "chunk", "chunk(xs: list, n: int) -> list[list]. Split xs into consecutive chunks of size n; the last may be shorter.",
         ["assert chunk([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]", "assert chunk([], 3) == []"],
         "def chunk(xs, n):\n    return [xs[i:i + n] for i in range(0, len(xs), n)]\n",
         "", ""),
    Task("t05", "max_gap", "max_gap(xs: list[int]) -> int. Largest difference between neighbours after sorting. Return 0 when fewer than two items.",
         ["assert max_gap([1, 9, 3]) == 6", "assert max_gap([]) == 0", "assert max_gap([4]) == 0"],
         "def max_gap(xs):\n    s = sorted(xs)\n    if len(s) < 2:\n        return 0\n    return max(b - a for a, b in zip(s, s[1:]))\n",
         "def max_gap(xs):\n    s = sorted(xs)\n    return max(b - a for a, b in zip(s, s[1:]))\n", "empty"),
    Task("t06", "is_anagram", "is_anagram(a: str, b: str) -> bool. True if a and b are anagrams, ignoring spaces and letter case.",
         ["assert is_anagram('Listen', 'Silent')", "assert not is_anagram('ab', 'abc')", "assert is_anagram('a b', 'BA')"],
         "def is_anagram(a, b):\n    f = lambda s: sorted(s.replace(' ', '').lower())\n    return f(a) == f(b)\n",
         "def is_anagram(a, b):\n    f = lambda s: sorted(s.replace(' ', ''))\n    return f(a) == f(b)\n", "case"),
    Task("t07", "to_binary", "to_binary(n: int) -> str. Binary string without the 0b prefix; negative numbers get a leading '-'.",
         ["assert to_binary(5) == '101'", "assert to_binary(-5) == '-101'", "assert to_binary(0) == '0'"],
         "def to_binary(n):\n    s = bin(abs(n))[2:]\n    return '-' + s if n < 0 else s\n",
         "def to_binary(n):\n    return bin(n)[2:]\n", "negative"),
    Task("t08", "first_unique", "first_unique(s: str) -> str | None. First character that occurs exactly once; None if there is none (including empty input).",
         ["assert first_unique('aabcb') == 'c'", "assert first_unique('') is None", "assert first_unique('aa') is None"],
         "def first_unique(s):\n    for c in s:\n        if s.count(c) == 1:\n            return c\n    return None\n",
         "def first_unique(s):\n    return next(c for c in s if s.count(c) == 1)\n", "empty"),
    Task("t09", "clamp_all", "clamp_all(xs: list[float], lo: float, hi: float) -> list[float]. Clamp every value into [lo, hi].",
         ["assert clamp_all([-1, 5, 11], 0, 10) == [0, 5, 10]", "assert clamp_all([], 0, 1) == []"],
         "def clamp_all(xs, lo, hi):\n    return [min(max(x, lo), hi) for x in xs]\n",
         "", ""),
    Task("t10", "count_vowels", "count_vowels(s: str) -> int. Number of vowels a, e, i, o, u in s, case-insensitive.",
         ["assert count_vowels('AEiou') == 5", "assert count_vowels('xyz') == 0"],
         "def count_vowels(s):\n    return sum(c in 'aeiou' for c in s.lower())\n",
         "def count_vowels(s):\n    return sum(c in 'aeiou' for c in s)\n", "case"),
    Task("t11", "median", "median(xs: list[float]) -> float | None. Median of xs (mean of the two middle values for even length). None for an empty list.",
         ["assert median([3, 1, 2]) == 2", "assert median([1, 2, 3, 4]) == 2.5", "assert median([]) is None"],
         "def median(xs):\n    if not xs:\n        return None\n    s = sorted(xs)\n    m = len(s) // 2\n    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2\n",
         "def median(xs):\n    s = sorted(xs)\n    m = len(s) // 2\n    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2\n", "empty"),
    Task("t12", "reverse_digits", "reverse_digits(n: int) -> int. Reverse the decimal digits of n, keeping its sign (-123 -> -321).",
         ["assert reverse_digits(123) == 321", "assert reverse_digits(-120) == -21", "assert reverse_digits(0) == 0"],
         "def reverse_digits(n):\n    r = int(str(abs(n))[::-1])\n    return -r if n < 0 else r\n",
         "def reverse_digits(n):\n    return int(str(n)[::-1])\n", "negative"),
]

STYLE_GUIDE = """Relaypack house coding guide (applies to every task).
1. Functions are pure: no printing, no global state, no input().
2. Use only the Python standard library.
3. Name things plainly; prefer comprehensions over manual index loops when they read better.
4. Every public function documents its edge cases in the spec; implement each edge case exactly as written.
5. Do not raise on edge cases that the spec gives a default for.
6. Keep each solution under 15 lines.
7. Integers stay integers; only return float where the spec says float.
8. Treat strings as Unicode text; never assume ASCII-only unless the spec says so.
9. Prefer early returns for edge cases at the top of the function.
10. Tests are hidden: reason about edge cases from the spec, not from examples.
""" + "\n".join(
    f"Appendix {i}: worked example of a reviewed function, kept for reference. "
    "The reviewer checks naming, edge cases, purity and length against the rules above, "
    "and records any recurring defect as a team lesson."
    for i in range(1, 25)
)

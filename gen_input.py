#!/usr/bin/env python3
"""Generate a deterministic benchmark input: balanced semiprimes p*q.

Trial division has to scan every odd candidate up to the smallest prime
factor p, so a product of two primes of similar size (p, q ~ 10^9) is the
worst case and gives a stable, reproducible amount of work.
"""
import argparse
import random


def is_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def random_prime(rng, lo, hi):
    while True:
        c = rng.randrange(lo, hi) | 1
        if is_prime(c):
            return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--lo", type=int, default=400_000_000)
    ap.add_argument("--hi", type=int, default=1_000_000_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="input.txt")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    with open(a.out, "w") as f:
        f.write("# %d semiprimes p*q with p,q primes in [%d, %d), seed %d\n" % (a.count, a.lo, a.hi, a.seed))
        for _ in range(a.count):
            p = random_prime(rng, a.lo, a.hi)
            q = random_prime(rng, a.lo, a.hi)
            f.write("%d\n" % (p * q))
            print(p * q, "=", min(p, q), "*", max(p, q))


if __name__ == "__main__":
    main()

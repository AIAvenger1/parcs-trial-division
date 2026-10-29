# -*- coding: utf-8 -*-
# Factorization by trial division, parallel version for PARCS-Python.
#
# Idea
# ----
# Trial division tests candidate divisors d = 2, 3, 5, 7, ... up to sqrt(n).
# Every candidate is independent of the others, so the range of candidates
# can be cut into pieces and every piece can be checked on a different
# worker. The master cuts [3, sqrt(n)] into chunks of CHUNK odd candidates,
# keeps a queue of chunks and hands the next chunk to whichever worker
# becomes free first (dynamic scheduling, no worker waits for the others).
#
# A worker receives (n, lo, hi) and returns every odd d in [lo, hi) with
# n % d == 0. The master sorts the reported divisors and divides them out of
# n in increasing order. A composite divisor (say 15 = 3 * 5) is reported
# as well, but by the time the master reaches it, 3 and 5 have already been
# divided out, so n % 15 != 0 and it is skipped. Whatever is left of n
# after all chunks up to sqrt(n) are checked is prime (or 1).
#
# When a factor is found, sqrt(n) shrinks, so chunks beyond the new limit
# are dropped from the queue (pruning). Chunks that are already running are
# allowed to finish, their extra divisors are harmless.
#
# The code must stay Python-2.7 compatible: the PARCS-Python core is py2-only.
from Pyro4 import expose
from collections import deque
import time

# Odd candidates per worker call (range width is 2 * CHUNK), ~0.4 s of work.
CHUNK = 2000000


def isqrt(n):
    # Integer square root (floor) by Newton's method, exact for big ints.
    if n < 2:
        return n
    x = int(n ** 0.5)
    while x * x > n:
        x -= 1
    while (x + 1) * (x + 1) <= n:
        x += 1
    return x


class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers

    # ----------------------------------------------------------------- master
    def solve(self):
        start = time.time()
        numbers = self.read_input()
        print("Workers %d, numbers %d" % (len(self.workers), len(numbers)))

        self.factors = [[] for _ in numbers]   # prime factors of numbers[i]
        self.rest = []                         # unfactored part of numbers[i]
        self.limit = []                        # isqrt(rest[i])
        self.found = [[] for _ in numbers]     # divisors reported by workers
        self.pending = [0] * len(numbers)      # chunks still running
        self.queued = [0] * len(numbers)       # chunks still in the queue
        self.queue = deque()                   # (i, lo, hi) chunks to do

        chunks = []
        for i, n in enumerate(numbers):
            # Factor 2 is cheap and makes every later candidate odd.
            while n % 2 == 0:
                self.factors[i].append(2)
                n //= 2
            self.rest.append(n)
            self.limit.append(isqrt(n))
            chunks.append([])
            lo = 3
            while lo <= self.limit[i]:
                hi = min(lo + 2 * CHUNK, self.limit[i] + 1)
                chunks[i].append((i, lo, hi))
                lo = hi
            if not chunks[i]:
                # Nothing to check: n is 1 or a prime below 9.
                self.finish(i)

        # Round-robin: chunk k of every number goes before chunk k+1 of any.
        # So when a factor of number i is found, the chunks of i that are
        # already running are few (the rest of the workers hold other
        # numbers) and the pruned chunks have not been dispatched yet.
        k = 0
        while any(len(c) > k for c in chunks):
            for i in range(len(numbers)):
                if len(chunks[i]) > k:
                    self.queue.append(chunks[i][k])
                    self.queued[i] += 1
            k += 1

        calls = self.run()

        self.write_output(numbers, calls, time.time() - start)
        print("Job finished, %d worker calls, %.2f s" % (calls, time.time() - start))

    def run(self):
        # Dynamic scheduling: every free worker immediately gets the next
        # chunk. Calls are asynchronous (Pyro4 futures), so all workers run
        # at the same time and the master only collects results.
        busy = {}
        calls = 0
        while self.queue or busy:
            for w in range(len(self.workers)):
                if w not in busy and self.queue:
                    i, lo, hi = task = self.queue.popleft()
                    self.queued[i] -= 1
                    self.pending[i] += 1
                    # Big ints are sent as strings to avoid serializer limits.
                    future = self.workers[w].find_divisors(str(self.rest[i]), str(lo), str(hi))
                    busy[w] = (task, future)
                    calls += 1
            time.sleep(0.005)
            for w in list(busy):
                task, future = busy[w]
                if future.ready:
                    del busy[w]
                    self.handle(task, future.value)
        return calls

    def handle(self, task, divisors):
        i, lo, hi = task
        self.pending[i] -= 1
        if divisors:
            self.found[i].extend(int(d) for d in divisors)
            self.reduce(i)
        if self.pending[i] == 0 and self.queued[i] == 0:
            self.finish(i)

    def reduce(self, i):
        # Divide out reported divisors in increasing order; composites are
        # skipped automatically because their prime parts went first.
        self.found[i].sort()
        n = self.rest[i]
        for d in self.found[i]:
            while n % d == 0:
                self.factors[i].append(d)
                n //= d
        self.found[i] = []
        if n != self.rest[i]:
            self.rest[i] = n
            self.limit[i] = isqrt(n)
            self.prune(i)

    def prune(self, i):
        # The limit shrank: drop queued chunks of number i that start above it.
        kept = deque()
        for (j, lo, hi) in self.queue:
            if j == i and lo > self.limit[i]:
                self.queued[i] -= 1
            else:
                kept.append((j, lo, hi))
        self.queue = kept

    def finish(self, i):
        if self.rest[i] > 1:
            self.factors[i].append(self.rest[i])
            self.rest[i] = 1
        self.factors[i].sort()

    # ----------------------------------------------------------------- worker
    @staticmethod
    @expose
    def find_divisors(n, lo, hi):
        # Return every odd d in [lo, hi) that divides n.
        n = int(n)
        lo = int(lo)
        hi = int(hi)
        if lo % 2 == 0:
            lo += 1
        result = []
        d = lo
        while d < hi:
            if n % d == 0:
                result.append(str(d))
            d += 2
        return result

    # -------------------------------------------------------------------- io
    def read_input(self):
        numbers = []
        f = open(self.input_file_name, 'r')
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                numbers.append(int(line))
        f.close()
        return numbers

    def write_output(self, numbers, calls, seconds):
        f = open(self.output_file_name, 'w')
        for n, fs in zip(numbers, self.factors):
            if n < 2:
                f.write('%d\n' % n)
            else:
                f.write('%d = %s\n' % (n, ' * '.join(str(p) for p in fs)))
        f.write('workers: %d, calls: %d, time: %.2f s\n' % (len(self.workers), calls, seconds))
        f.close()

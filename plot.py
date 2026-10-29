#!/usr/bin/env python3
"""results/results.csv -> results/plot.png (time + speedup) and results/table.md"""
import csv
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

runs = defaultdict(list)
for r in csv.DictReader(open("results/results.csv")):
    runs[int(r["workers"])].append(float(r["seconds"]))
ws = sorted(runs)
mean = {w: sum(runs[w]) / len(runs[w]) for w in ws}
t1 = mean[ws[0]] * ws[0]
speed = {w: t1 / mean[w] for w in ws}

with open("results/table.md", "w") as f:
    f.write("| Воркери | Час, с (сер.) | min / max, с | Прискорення | Ефективність |\n|---:|---:|---:|---:|---:|\n")
    for w in ws:
        f.write("| %d | %.1f | %.1f / %.1f | %.2f | %.2f |\n" % (w, mean[w], min(runs[w]), max(runs[w]), speed[w], speed[w] / w))
print(open("results/table.md").read())

fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4), dpi=150)
a1.plot(ws, [mean[w] for w in ws], "o-", color="#1f5fbf")
for w in ws:
    a1.plot([w] * len(runs[w]), runs[w], ".", color="#1f5fbf", alpha=0.4)
a1.set_xlabel("Кількість воркерів"); a1.set_ylabel("Час, с"); a1.set_title("Час виконання")
a1.set_xticks(ws); a1.grid(alpha=0.3); a1.set_ylim(bottom=0)
a2.plot(ws, [speed[w] for w in ws], "o-", color="#1f5fbf", label="виміряне")
a2.plot(ws, ws, "--", color="#999", label="ідеальне")
a2.set_xlabel("Кількість воркерів"); a2.set_ylabel("Прискорення"); a2.set_title("Прискорення")
a2.set_xticks(ws); a2.grid(alpha=0.3); a2.legend()
fig.tight_layout(); fig.savefig("results/plot.png")
print("saved results/plot.png")

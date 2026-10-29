#!/usr/bin/env python3
"""Submit the trial-division job to a PARCS master for several worker counts
and record the wall time reported by the solver.

Local cluster (docker compose) - the script scales the workers itself:
    python3 benchmark.py --workers 1 2 4 8 --runs 3

Cloud cluster - start/stop worker VMs yourself (or with gcp/scale.sh), then:
    python3 benchmark.py --master http://<MASTER_IP>:8080 --no-scale --workers 4
"""
import argparse
import csv
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


def workers_online(master):
    import json
    _, body = http(master + "/api/worker")
    return [w for w in json.loads(body)["workers"] if w["enabled"]]


def wait_for_workers(master, n, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            ws = workers_online(master)
            if len(ws) == n:
                time.sleep(2)   # let late registrations settle
                if len(workers_online(master)) == n:
                    return ws
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("expected %d workers, have %d" % (n, len(workers_online(master))))


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    for k, (name, content) in files.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n" % (boundary, k, name)).encode()
        body += content + b"\r\n"
    body += ("--%s--\r\n" % boundary).encode()
    return body, {"Content-Type": "multipart/form-data; boundary=" + boundary}


def submit(master, name, solution, inp):
    body, hdr = multipart({"job_name": name},
                          {"solution_file": ("solution.py", open(solution, "rb").read()),
                           "input_file": ("input.txt", open(inp, "rb").read())})
    http(master + "/api/job", body, hdr)


def job_ids(master):
    # Job ids are sequential; the jobs page lists them as /api/job/<id>/output links.
    _, page = http(master + "/jobs")
    return sorted(set(int(x) for x in re.findall(rb"/api/job/(\d+)/", page)))


def wait_output(master, job_id, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            status, body = http(master + "/api/job/%d/output" % job_id)
            if status == 200:
                return body.decode()
        except urllib.error.HTTPError as e:
            if e.code != 400:      # 400 = not finished yet
                raise
        time.sleep(1)
    raise SystemExit("job %d did not finish in %ds" % (job_id, timeout))


def scale(n):
    subprocess.run(["docker", "compose", "up", "-d", "--scale", "worker=%d" % n], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="http://localhost:8080")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--solution", default="solution.py")
    ap.add_argument("--input", default="input.txt")
    ap.add_argument("--out", default="results/results.csv")
    ap.add_argument("--no-scale", action="store_true", help="do not run docker compose --scale")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()

    rows = []
    for n in a.workers:
        if not a.no_scale:
            scale(n)
        ws = wait_for_workers(a.master, n)
        print("== %d workers online: %s" % (n, ", ".join("%s:%s" % (w["ip"], w["port"]) for w in ws)))
        for r in range(a.runs):
            before = job_ids(a.master)
            submit(a.master, "td-w%d-r%d" % (n, r), a.solution, a.input)
            time.sleep(1)
            new = [j for j in job_ids(a.master) if j not in before]
            job = max(new) if new else (max(before) + 1 if before else 0)
            out = wait_output(a.master, job, a.timeout)
            m = re.search(r"workers: (\d+), calls: (\d+), time: ([\d.]+) s", out)
            used, calls, secs = int(m.group(1)), int(m.group(2)), float(m.group(3))
            if used != n:
                print("WARNING: solver saw %d workers, expected %d" % (used, n))
            print("   run %d: job %d, %.2f s, %d calls" % (r + 1, job, secs, calls))
            rows.append({"workers": n, "run": r + 1, "job": job, "seconds": secs, "calls": calls})
            with open("results/last_output_w%d.txt" % n, "w") as f:
                f.write(out)
    import os
    os.makedirs("results", exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["workers", "run", "job", "seconds", "calls"])
        w.writeheader()
        w.writerows(rows)
    print("saved", a.out)


if __name__ == "__main__":
    sys.exit(main())

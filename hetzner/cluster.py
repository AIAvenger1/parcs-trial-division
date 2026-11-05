#!/usr/bin/env python3
"""PARCS-Python cluster in Hetzner Cloud: one master and N worker VMs.

    python3 hetzner/cluster.py up [--workers 4]   create network, firewall and VMs
    python3 hetzner/cluster.py provision [--per-vm 2]   set up NAT, install Docker, start the nodes
    python3 hetzner/cluster.py status             list nodes (also writes hetzner/nodes.json)
    python3 hetzner/cluster.py scale N            leave exactly N worker processes running
    python3 hetzner/cluster.py tunnel             print the SSH tunnel command for the web UI
    python3 hetzner/cluster.py down               delete everything this script created

The API token is read from $HCLOUD_TOKEN or ~/.hcloud-token (Hetzner console:
Security -> API tokens, Read & Write). Only resources labelled project=parcs-lab1
are ever touched, so other servers in the same project are safe.

Layout and security model
  * A worker VM can host several worker processes (--per-vm), each pinned to its
    own vCPU: a Hetzner project is limited to a few servers, and a PARCS worker is
    single-threaded, so one process per core uses the VM fully.
  * Only the master has a public address. Workers live in the private network
    10.10.0.0/24 and reach the internet through the master (NAT), so the cluster
    needs one public IP no matter how many workers it has.
  * The PARCS web UI executes any uploaded code and has no login, so it is never
    exposed: the cloud firewall admits only SSH, and the UI is reached through an
    SSH tunnel. Workers are reached over SSH by jumping through the master.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.hetzner.cloud/v1"
LABEL = "parcs-lab1"
SELECTOR = "project=" + LABEL
NET_RANGE, SUBNET, GATEWAY = "10.10.0.0/16", "10.10.0.0/24", "10.10.0.1"
DNS = "185.12.64.2 185.12.64.1"            # Hetzner recursive resolvers
HERE = Path(__file__).resolve().parent
NODES_FILE = HERE / "nodes.json"
SSH_KEY_FILE = os.environ.get("PARCS_SSH_KEY", os.path.expanduser("~/.ssh/hetzner_minidrive"))
SSH_KEY_NAME = os.environ.get("PARCS_SSH_KEY_NAME", "minidrive-hetzner")   # name of the key in the Hetzner project
SSH_OPTS = ["-i", SSH_KEY_FILE, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR"]

# Runs on the master: forward and masquerade traffic of the private network.
# Docker sets the FORWARD policy to DROP, hence the explicit ACCEPT rules.
NAT_SCRIPT = r"""#!/bin/sh
OUT=$(ip route show default | awk '{print $5; exit}')
sysctl -qw net.ipv4.ip_forward=1
iptables -t nat -C POSTROUTING -s %(net)s -o $OUT -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s %(net)s -o $OUT -j MASQUERADE
for chain in FORWARD DOCKER-USER; do
  iptables -nL $chain >/dev/null 2>&1 || continue
  iptables -C $chain -s %(net)s -j ACCEPT 2>/dev/null || iptables -I $chain -s %(net)s -j ACCEPT
  iptables -C $chain -d %(net)s -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -I $chain -d %(net)s -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
done
""" % {"net": NET_RANGE}
NAT_UNIT = """[Unit]
Description=NAT for the PARCS private network
After=network-online.target docker.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/parcs-nat.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
"""


def token():
    t = os.environ.get("HCLOUD_TOKEN")
    if not t:
        p = Path.home() / ".hcloud-token"
        t = p.read_text().strip() if p.exists() else ""
    if not t:
        sys.exit("no API token: set HCLOUD_TOKEN or put it into ~/.hcloud-token")
    return t


class ApiError(Exception):
    pass


def api(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise ApiError("Hetzner API %s %s -> %s %s" % (method, path, e.code, e.read().decode()[:300]))


def servers():
    nodes = []
    for s in api("GET", "/servers?label_selector=" + SELECTOR)["servers"]:
        v4 = s["public_net"].get("ipv4")
        nodes.append({"id": s["id"], "name": s["name"], "status": s["status"], "type": s["server_type"]["name"],
                      "public": v4["ip"] if v4 else None,
                      "private": s["private_net"][0]["ip"] if s["private_net"] else None})
    return sorted(nodes, key=lambda n: (0 if n["name"].endswith("master") else 1, len(n["name"]), n["name"]))


def master_and_workers():
    nodes = servers()
    master = [n for n in nodes if n["name"].endswith("master")]
    if not master:
        sys.exit("no cluster: run `cluster.py up` first")
    return master[0], [n for n in nodes if not n["name"].endswith("master")]


def ssh_target(node, master):
    """ssh arguments for a node: the master directly, a worker by jumping through the master."""
    if node["public"]:
        return [*SSH_OPTS, "root@" + node["public"]]
    jump = "ssh %s -W %%h:%%p root@%s" % (" ".join(SSH_OPTS), master["public"])
    return [*SSH_OPTS, "-o", "ProxyCommand=" + jump, "root@" + node["private"]]


def ssh(node, master, command, check=True, stdin=None):
    r = subprocess.run(["ssh", *ssh_target(node, master), command], capture_output=True, text=True, input=stdin)
    if check and r.returncode != 0:
        raise RuntimeError("%s: %s" % (node["name"], (r.stderr or r.stdout).strip()[-400:]))
    return r.stdout.strip()


def wait_ssh(node, master, tries=40):
    for _ in range(tries):
        if subprocess.run(["ssh", *ssh_target(node, master), "true"], capture_output=True).returncode == 0:
            return
        time.sleep(5)
    raise RuntimeError("%s: not reachable over SSH" % node["name"])


def cmd_up(a):
    existing = {n["name"] for n in servers()}
    nets = api("GET", "/networks?label_selector=" + SELECTOR)["networks"]
    net = nets[0] if nets else api("POST", "/networks", {
        "name": LABEL, "ip_range": NET_RANGE, "labels": {"project": LABEL},
        "subnets": [{"type": "cloud", "ip_range": SUBNET, "network_zone": "eu-central"}]})["network"]
    if not api("GET", "/firewalls?label_selector=" + SELECTOR)["firewalls"]:
        # SSH only. Node-to-node traffic uses the private network, which this firewall does not filter.
        api("POST", "/firewalls", {
            "name": LABEL, "labels": {"project": LABEL},
            "rules": [{"direction": "in", "protocol": "tcp", "port": "22", "source_ips": ["0.0.0.0/0", "::/0"],
                       "description": "SSH (key only)"}],
            "apply_to": [{"type": "label_selector", "label_selector": {"selector": SELECTOR}}]})
    names = ["parcs-master"] + ["parcs-worker%d" % i for i in range(1, a.workers + 1)]
    for name in names:
        if name in existing:
            continue
        is_master = name.endswith("master")
        api("POST", "/servers", {
            "name": name, "server_type": a.type, "image": a.image, "location": a.location,
            "ssh_keys": [SSH_KEY_NAME], "networks": [net["id"]], "labels": {"project": LABEL},
            "public_net": {"enable_ipv4": is_master, "enable_ipv6": False},
            "start_after_create": True})
        print("created", name, "(public IPv4)" if is_master else "(private network only)")
    print("waiting for the VMs to start...")
    for _ in range(60):
        nodes = servers()
        if len(nodes) == len(names) and all(n["status"] == "running" and n["private"] for n in nodes):
            break
        time.sleep(5)
    master, _ = master_and_workers()
    # send the workers' internet traffic to the master
    net = api("GET", "/networks/%d" % net["id"])["network"]
    if not any(r["destination"] == "0.0.0.0/0" for r in net["routes"]):
        api("POST", "/networks/%d/actions/add_route" % net["id"], {"destination": "0.0.0.0/0", "gateway": master["private"]})
    cmd_status(a)


def cmd_status(a):
    nodes = servers()
    NODES_FILE.write_text(json.dumps(nodes, indent=1))
    print("%-15s %-9s %-6s %-16s %s" % ("NAME", "STATUS", "TYPE", "PUBLIC IP", "PRIVATE IP"))
    for n in nodes:
        print("%-15s %-9s %-6s %-16s %s" % (n["name"], n["status"], n["type"], n["public"] or "-", n["private"]))


def start_node(node, master, per_vm=1):
    rsync_ssh = "ssh " + " ".join("'%s'" % x if " " in x else x for x in ssh_target(node, master)[:-1])
    host = ssh_target(node, master)[-1]
    subprocess.run(["rsync", "-az", "--delete", "-e", rsync_ssh,
                    str(HERE.parent / "parcs-python") + "/", host + ":/opt/parcs-python/"], check=True)
    ssh(node, master, "cd /opt/parcs-python && docker build -q -t parcs-node . >/dev/null")
    # host networking: the node registers with (and is called back on) its private address
    run = ("docker run -d --name %s --restart unless-stopped --network host %s "
           "-e PARCS_ARGS='%s' -e PARCS_IP=" + node["private"] + " parcs-node >/dev/null")
    ssh(node, master, "docker rm -f $(docker ps -aq --filter name=parcs) >/dev/null 2>&1 || true")
    if node is master:
        ssh(node, master, run % ("parcs", "", "master"))
        return "%s: master started on %s" % (node["name"], node["private"])
    for k in range(per_vm):          # one single-threaded worker process per vCPU
        ssh(node, master, run % ("parcs-%d" % (k + 1), "--cpuset-cpus %d" % k, "worker " + master["private"]))
    return "%s: %d worker(s) started on %s" % (node["name"], per_vm, node["private"])


def provision_master(master):
    wait_ssh(master, master)
    ssh(master, master, "cloud-init status --wait >/dev/null 2>&1 || true")
    ssh(master, master, "cat > /usr/local/sbin/parcs-nat.sh && chmod +x /usr/local/sbin/parcs-nat.sh", stdin=NAT_SCRIPT)
    ssh(master, master, "cat > /etc/systemd/system/parcs-nat.service", stdin=NAT_UNIT)
    ssh(master, master, "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null && "
                        "apt-get install -y -qq docker.io rsync >/dev/null 2>&1 && systemctl enable --now docker >/dev/null 2>&1 && "
                        "systemctl daemon-reload && systemctl enable --now parcs-nat.service >/dev/null 2>&1 && /usr/local/sbin/parcs-nat.sh")
    return start_node(master, master)


def provision_worker(worker, master, per_vm=1):
    wait_ssh(worker, master)
    # no public address: default route and DNS go through the private network gateway
    ssh(worker, master,
        "ip route replace default via %(gw)s && "
        "mkdir -p /etc/systemd/resolved.conf.d && printf '[Resolve]\\nDNS=%(dns)s\\n' > /etc/systemd/resolved.conf.d/parcs.conf && "
        "systemctl restart systemd-resolved && "
        "printf '@reboot root sleep 5; ip route replace default via %(gw)s\\n' > /etc/cron.d/parcs-route" % {"gw": GATEWAY, "dns": DNS})
    ssh(worker, master, "cloud-init status --wait >/dev/null 2>&1 || true; export DEBIAN_FRONTEND=noninteractive; "
                        "apt-get update -qq >/dev/null && apt-get install -y -qq docker.io rsync >/dev/null 2>&1 && "
                        "systemctl enable --now docker >/dev/null 2>&1")
    return start_node(worker, master, per_vm)


def cmd_provision(a):
    master, workers = master_and_workers()
    print(provision_master(master))
    with ThreadPoolExecutor(8) as pool:
        for line in pool.map(lambda w: provision_worker(w, master, a.per_vm), workers):
            print(line)


def cmd_scale(a):
    master, workers = master_and_workers()
    per_vm = {w["name"]: sorted(ssh(w, master, "docker ps -a --format '{{.Names}}' --filter name=parcs-").split()) for w in workers}
    # fill the VMs evenly: the first process of every VM, then the second of every VM, ...
    depth = max(len(c) for c in per_vm.values())
    slots = [(w, per_vm[w["name"]][k]) for k in range(depth) for w in workers if len(per_vm[w["name"]]) > k]
    for i, (w, container) in enumerate(slots):
        ssh(w, master, ("docker start %s" if i < a.n else "docker stop -t 2 %s") % container + " >/dev/null 2>&1 || true")
    print("running workers:", ", ".join("%s/%s" % (w["name"], c) for w, c in slots[:a.n]) or "none")


def cmd_tunnel(a):
    master, _ = master_and_workers()
    print("ssh -i %s -N -L %d:%s:8080 root@%s" % (SSH_KEY_FILE, a.port, master["private"], master["public"]))
    print("# then open http://localhost:%d" % a.port)


def cmd_down(a):
    for s in servers():
        api("DELETE", "/servers/%d" % s["id"])
        print("deleted", s["name"])
    for _ in range(30):                       # firewall and network can go once the VMs are gone
        if not servers():
            break
        time.sleep(3)
    for kind in ("firewalls", "networks"):
        for r in api("GET", "/%s?label_selector=%s" % (kind, SELECTOR))[kind]:
            for _ in range(10):
                try:
                    api("DELETE", "/%s/%d" % (kind, r["id"]))
                    print("deleted", kind[:-1], r["name"])
                    break
                except ApiError:
                    time.sleep(3)
    NODES_FILE.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up")
    up.add_argument("--workers", type=int, default=4, help="number of worker VMs")
    up.add_argument("--type", default="cx23")
    up.add_argument("--location", default="hel1")
    up.add_argument("--image", default="ubuntu-24.04")
    pv = sub.add_parser("provision")
    pv.add_argument("--per-vm", type=int, default=1, help="worker processes per worker VM (one per vCPU)")
    sub.add_parser("status")
    sc = sub.add_parser("scale")
    sc.add_argument("n", type=int)
    tn = sub.add_parser("tunnel")
    tn.add_argument("--port", type=int, default=8081)
    sub.add_parser("down")
    a = ap.parse_args()
    try:
        globals()["cmd_" + a.cmd](a)
    except (ApiError, RuntimeError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

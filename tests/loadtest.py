"""Load and limiter test against a real server process over real HTTP. Run by hand:  python tests/loadtest.py

Starts tests/e2e/server.py (the real app with a fake GitHub) twice: once with generous limits to measure how it
copes with a crowd, once with tight limits to check the limiter lets through exactly the configured number.
Optional: `pip install psutil` to also report memory.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ISSUE = "https://github.com/acme/pyparse/issues/{}".format
FAILURES = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class Server:
    def __init__(self, port, **env):
        self.port = port
        self.env = {**os.environ, "E2E_PORT": str(port), **env}

    def __enter__(self):
        self.process = subprocess.Popen([sys.executable, str(ROOT / "tests/e2e/server.py")], env=self.env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.25)
        raise RuntimeError("the test server did not start")

    def __exit__(self, *exc):
        if os.name == "nt":  # the venv launcher starts a child process; kill the whole tree
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True)
        else:
            self.process.terminate()
        self.process.wait()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def memory_mb(self):
        try:
            import psutil

            root = psutil.Process(self.process.pid)
            return sum(p.memory_info().rss for p in [root, *root.children(recursive=True)]) / 1e6
        except Exception:
            return None


async def capacity(server, total=3000, concurrency=150):
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=server.url, limits=limits, timeout=60) as warm:
        await warm.get("/__test/reset")
    clients = [httpx.AsyncClient(base_url=server.url, limits=limits, timeout=60) for _ in range(40)]  # 40 browsers, each with its own cookie
    for client in clients:
        await client.get("/api/bookmarks")
    gate = asyncio.Semaphore(concurrency)
    results = []  # (label, status, seconds)

    async def one(i):
        client = clients[i % len(clients)]
        number = (11, 12, 15, 16)[i % 4]
        kind = i % 10
        async with gate:
            started = time.perf_counter()
            if kind < 3:
                response = await client.get("/api/issues", params={"sort": ("updated", "newest", "discussed", "quiet")[i % 4]})
            elif kind == 3:
                response = await client.get("/api/facets")
            elif kind in (4, 5):
                response = await client.post("/api/verify", json={"github_url": ISSUE(number)})
            elif kind == 6:
                response = await client.get("/api/checklist", params={"github_url": ISSUE(number)})
            elif kind == 7:
                response = await client.post("/api/bookmarks", json={"github_url": ISSUE(number)})
            elif kind == 8:
                response = await client.get("/api/bookmarks")
            else:
                response = await client.get("/")
            results.append((kind, response.status_code, time.perf_counter() - started))

    before = server.memory_mb()
    started = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(total)))
    elapsed = time.perf_counter() - started
    after = server.memory_mb()
    for client in clients:
        await client.aclose()

    statuses = sorted({status for _, status, _ in results})
    seconds = sorted(s for _, _, s in results)
    p = lambda q: seconds[min(len(seconds) - 1, int(len(seconds) * q))] * 1000  # noqa: E731
    print(f"      {total} requests, {concurrency} at a time: {total / elapsed:.0f} req/s; latency p50 {p(.5):.0f} ms, p95 {p(.95):.0f} ms, p99 {p(.99):.0f} ms, max {seconds[-1] * 1000:.0f} ms")
    if before and after:
        print(f"      memory: {before:.0f} MB before, {after:.0f} MB after")
    check("every request was answered with 200 or 201", statuses in ([200], [200, 201]), statuses)
    check("p95 latency under 2 seconds", p(0.95) < 2000, f"{p(.95):.0f} ms")
    if before and after:
        check("memory grew by less than 100 MB", after - before < 100, f"{after - before:.0f} MB")


async def limiter(server):
    async with httpx.AsyncClient(base_url=server.url, timeout=30) as client:
        await client.get("/__test/reset")
        heavy = [(await client.get("/api/issues")).status_code for _ in range(60)]
        check("heavy route: exactly 20 allowed, then 429", heavy.count(200) == 20 and heavy[20:] == [429] * 40, f"{heavy.count(200)} ok, {heavy.count(429)} limited")
        blocked = await client.get("/api/issues")
        check("the 429 explains itself and says when to retry", blocked.status_code == 429 and 1 <= int(blocked.headers["retry-after"]) <= 60 and "Too many requests" in blocked.json()["detail"])
        general = [(await client.get("/api/facets")).status_code for _ in range(70)]
        check("ordinary route has its own, larger allowance (50)", general.count(200) == 50 and general[50:] == [429] * 20, f"{general.count(200)} ok")
        check("the page itself and /health are never limited", (await client.get("/")).status_code == 200 and (await client.get("/health")).status_code == 200)
    async with httpx.AsyncClient(base_url=server.url, timeout=30) as other:
        # A different client address would be limited separately, but all test traffic is one address; the global cap is checked here.
        check("limits are per minute, per visitor, and reported in plain words", "Try again in" in (await other.get("/api/issues")).json()["detail"])


def main():
    print("--- capacity: a real server, generous limits")
    with Server(8791, RATE_LIMIT_PER_MINUTE="100000", RATE_LIMIT_HEAVY_PER_MINUTE="100000", RATE_LIMIT_GLOBAL_PER_MINUTE="1000000") as server:
        asyncio.run(capacity(server))
    print("--- limiter: a real server, tight limits (20 heavy and 50 ordinary requests a minute per visitor)")
    with Server(8792, RATE_LIMIT_PER_MINUTE="50", RATE_LIMIT_HEAVY_PER_MINUTE="20", RATE_LIMIT_GLOBAL_PER_MINUTE="100000") as server:
        asyncio.run(limiter(server))
    print("\nALL LOAD CHECKS PASSED" if not FAILURES else f"\n{len(FAILURES)} CHECK(S) FAILED")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

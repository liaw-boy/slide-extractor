#!/usr/bin/env python3
"""End-to-end smoke test for slide_web.py.

Exercises every critical user journey and prints PASS/FAIL per assertion.
Designed to find UX gaps, not algorithmic bugs (those are covered by unit
tests). Iterates fast because it reuses cached OCR for the M2 demo video.

Run:
    HOME=/home/eric python3 tests/smoke_web.py

Exit code 0 = all green; 1 = at least one assertion failed.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLIDE_WEB = ROOT / "slide_web.py"
DEMO_VIDEO = Path("/home/eric/slides_output/_video/M2 行動通訊安全 供應鏈安全不足錄.mp4")
OUTPUT_DIR = Path("/home/eric/slides_output")
PORT = 9911  # test-only port to avoid clashing with user's 8903
BASE = f"http://localhost:{PORT}"

PASS_MARK = "✓"
FAIL_MARK = "✗"
results: list[tuple[bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record an assertion."""
    results.append((condition, label))
    mark = PASS_MARK if condition else FAIL_MARK
    extra = f"  ({detail})" if detail else ""
    print(f"  {mark} {label}{extra}")


def wait_port(port: int, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def http_json(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def http_get_bytes(path: str) -> tuple[int, bytes, dict]:
    try:
        resp = urllib.request.urlopen(BASE + path, timeout=10)
        return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def poll_until_done(jid: str, max_wait: float = 120.0) -> dict:
    end = time.time() + max_wait
    last = {}
    while time.time() < end:
        _, last = http_json("GET", f"/api/job/{jid}")
        if last.get("status") in ("done", "error"):
            return last
        time.sleep(1.5)
    raise TimeoutError(f"job {jid} did not finish in {max_wait}s; last={last}")


def start_server(persist_path_to_preload: Path | None = None) -> subprocess.Popen:
    """Boot slide_web.py on PORT; return process handle."""
    if persist_path_to_preload and persist_path_to_preload != OUTPUT_DIR / "_jobs.json":
        # caller has set up _jobs.json; we use OUTPUT_DIR
        pass
    env = {**os.environ, "HOME": "/home/eric"}
    proc = subprocess.Popen(
        [sys.executable, str(SLIDE_WEB),
         "--port", str(PORT), "--bind", "127.0.0.1",
         "-o", str(OUTPUT_DIR)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if not wait_port(PORT, timeout=8):
        proc.kill()
        raise RuntimeError("server failed to bind in 8s")
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


# ───────────── tests ─────────────


def t1_input_validation():
    print("\n[T1] Input validation")
    code, body = http_json("POST", "/api/start", {})
    check("missing source rejected", code == 400 and not body.get("ok"))

    code, body = http_json("POST", "/api/start", {"source": "anything", "mode": "wrong"})
    check("invalid mode rejected", code == 400 and not body.get("ok"))

    code, body = http_json("POST", "/api/start", {"source": "/nonexistent.mp4", "mode": "auto"})
    # This one creates a job that errors during resolve; verify error path.
    check("non-existent path accepted (job created)", code == 200 and body.get("ok"))
    if body.get("ok"):
        final = poll_until_done(body["job_id"], max_wait=15)
        check(
            "non-existent path → job ends in error",
            final["status"] == "error" and "not found" in (final.get("error") or "").lower(),
        )


def t2_full_pipeline_local_file():
    print("\n[T2] Full pipeline (local cached video)")
    if not DEMO_VIDEO.exists():
        check("demo video present", False, f"missing {DEMO_VIDEO}")
        return None
    check("demo video present", True)

    code, body = http_json("POST", "/api/start",
                           {"source": str(DEMO_VIDEO), "mode": "auto"})
    check("start returns 200 + job_id", code == 200 and body.get("ok"))
    if not body.get("ok"):
        return None
    jid = body["job_id"]

    final = poll_until_done(jid, max_wait=120)
    check("job reaches done", final["status"] == "done", f"status={final['status']}")
    check("slides extracted", final["slide_count"] > 0, f"n={final['slide_count']}")
    check("progress total reflects sampling", final["progress_total"] >= 100)
    return jid


def t3_progress_fields(jid: str | None):
    print("\n[T3] Progress fields populated during run")
    if jid is None:
        check("(skipped — T2 failed)", False)
        return
    _, j = http_json("GET", f"/api/job/{jid}")
    for k in ("progress_current", "progress_total", "progress_label"):
        check(f"field {k} present", k in j)


def t4_auto_pptx_download(jid: str | None):
    print("\n[T4] Auto PPTX download with non-ASCII filename")
    if jid is None:
        check("(skipped)", False)
        return
    code, payload, headers = http_get_bytes(f"/job/{jid}/pptx")
    check("HTTP 200", code == 200)
    check("body is ZIP (PK magic)", payload[:2] == b"PK")
    check("Content-Disposition has filename*=UTF-8''",
          "filename*=UTF-8''" in headers.get("Content-Disposition", ""))


def t5_sheet_renders_with_nav(jid: str | None):
    print("\n[T5] Contact sheet rewrites + nav bar injection")
    if jid is None:
        check("(skipped)", False)
        return
    code, payload, _ = http_get_bytes(f"/job/{jid}/sheet")
    check("HTTP 200", code == 200)
    html = payload.decode("utf-8")
    check("nav '← 回到此 job 進度頁' injected", "回到此 job 進度頁" in html)
    check("nav '← 回到首頁' injected", "回到首頁" in html)
    check("nav href points to /job/<id>", f'href="/job/{jid}"' in html)
    check("nav href points to /", 'href="/"' in html)
    check("fetch URL rewritten to per-job finalize",
          f"/api/job/{jid}/finalize" in html)
    check("image src rewritten to per-job slides path",
          f'src="/job/{jid}/slides/' in html)


def t6_finalize_and_download(jid: str | None):
    print("\n[T6] Finalize POST + reviewed PPTX download")
    if jid is None:
        check("(skipped)", False)
        return
    # use first 3 slides as kept selection
    slides_dir = OUTPUT_DIR / "M2 行動通訊安全 供應鏈安全不足錄"
    if not slides_dir.exists():
        check("slides dir exists", False)
        return
    pngs = sorted(p.name for p in slides_dir.glob("slide_*.png"))[:3]
    code, body = http_json("POST", f"/api/job/{jid}/finalize", {"kept": pngs})
    check("finalize POST returns 200", code == 200 and body.get("ok"))
    check("finalize returns n=3", body.get("n") == 3)
    code, payload, headers = http_get_bytes(f"/job/{jid}/pptx_reviewed")
    check("reviewed PPTX HTTP 200", code == 200)
    check("reviewed PPTX is ZIP", payload[:2] == b"PK")
    check("reviewed Content-Disposition has UTF-8 filename",
          "filename*=UTF-8''" in headers.get("Content-Disposition", ""))


def t7_dashboard_lists_jobs(jid: str | None):
    print("\n[T7] Dashboard API + home page")
    if jid is None:
        check("(skipped)", False)
        return
    _, body = http_json("GET", "/api/jobs")
    check("/api/jobs returns list", body.get("ok") and isinstance(body.get("jobs"), list))
    ids = [j["id"] for j in body.get("jobs", [])]
    check("dashboard contains our job", jid in ids)
    code, html, _ = http_get_bytes("/")
    page = html.decode()
    check("home page has dashboard markup", "jobs-section" in page)
    check("home page has renderJobs JS", "renderJobs" in page)


def t8_progress_page_renders(jid: str | None):
    print("\n[T8] Progress page renders")
    if jid is None:
        check("(skipped)", False)
        return
    code, html, _ = http_get_bytes(f"/job/{jid}")
    check("HTTP 200", code == 200)
    page = html.decode()
    check("progress bar markup present", 'id="bar"' in page)
    check("ETA element present", 'id="eta"' in page)
    check("technical log collapsed by default", "<details class=\"tech\"" in page)


def t9_404_for_missing_job():
    print("\n[T9] 404 for unknown job id")
    code, body = http_json("GET", "/api/job/nonexistent")
    check("API returns 404", code == 404)
    code, payload, _ = http_get_bytes("/job/nonexistent")
    check("/job/<bad> returns 404", code == 404)


def t10_persistence_across_restart(jid: str | None):
    print("\n[T10] T-G05 — jobs persist across server restart")
    if jid is None:
        check("(skipped)", False)
        return None
    # Snapshot dashboard
    _, before = http_json("GET", "/api/jobs")
    before_ids = {j["id"] for j in before.get("jobs", [])}
    check("dashboard non-empty before restart", jid in before_ids)
    return before_ids


# ───────────── runner ─────────────


def main() -> int:
    print("════════════════════════════════════════════════")
    print("  slide_web.py smoke test")
    print("════════════════════════════════════════════════")

    # Wipe previous persistence file so this run starts clean
    persist = OUTPUT_DIR / "_jobs.json"
    if persist.exists():
        persist.unlink()

    proc = start_server()
    try:
        t1_input_validation()
        jid = t2_full_pipeline_local_file()
        t3_progress_fields(jid)
        t4_auto_pptx_download(jid)
        t5_sheet_renders_with_nav(jid)
        t6_finalize_and_download(jid)
        t7_dashboard_lists_jobs(jid)
        t8_progress_page_renders(jid)
        t9_404_for_missing_job()
        before_ids = t10_persistence_across_restart(jid)
    finally:
        stop_server(proc)

    # Persistence verification needs a fresh process
    print("\n[T10 cont.] Restart server and verify jobs reload")
    proc2 = start_server()
    try:
        _, after = http_json("GET", "/api/jobs")
        after_ids = {j["id"] for j in after.get("jobs", [])}
        check("_jobs.json now exists", persist.exists())
        check(
            "dashboard non-empty after restart",
            jid is None or (before_ids and after_ids >= before_ids),
            f"before={len(before_ids or [])} after={len(after_ids)}",
        )
        if jid:
            _, restored = http_json("GET", f"/api/job/{jid}")
            check("restored job still has slide_count",
                  restored.get("slide_count", 0) > 0)
    finally:
        stop_server(proc2)

    # Summary
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print("\n════════════════════════════════════════════════")
    print(f"  RESULT: {passed}/{total} passed")
    print("════════════════════════════════════════════════")
    if passed < total:
        print("\nFailing:")
        for ok, label in results:
            if not ok:
                print(f"  ✗ {label}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

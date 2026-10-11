#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool get token hàng loạt - 3 API, get lại TẤT CẢ acc
- Lưu TẤT CẢ token (JWT + hex) vào tokenlikes.txt
- Input : acc.txt (uid:password hoặc uid;password)
- Log   : error.txt
"""

import os
import sys
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

# ============ DANH SÁCH API ============
APIS = [
    "http://180.93.111.33:5002/token",
    "https://vipjwt.ffbot.site/token",
    "https://ags-community-jwt-api.vercel.app/token",
]

# ============ CẤU HÌNH ============
INPUT_FILE   = "acc.txt"
OUTPUT_FILE  = "tokenlikes.txt"
ERROR_FILE   = "error.txt"
DONE_FILE    = "done_uids.txt"

MAX_WORKERS  = 30       # tăng mạnh lên 30 luồng
DELAY        = 0.1      # gần như không nghỉ
TIMEOUT      = 20
MAX_RETRY    = 3
RETRY_WAIT   = 2.0
RESUME       = False    # ← TẮT RESUME = get lại TẤT CẢ acc

ERROR_THRESHOLD = 10
COOLDOWN        = 15.0
# ==================================


lock = threading.Lock()
api_stats = defaultdict(lambda: {"ok": 0, "fail": 0, "cooldown_until": 0.0, "consec_errors": 0})
api_rr_index = 0


def load_accounts(path):
    if not os.path.exists(path):
        print(f"[!] Không tìm thấy {path}")
        sys.exit(1)
    accounts, seen = [], set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sep = ":" if ":" in line else (";" if ";" in line else None)
            if sep is None:
                continue
            uid, pw = line.split(sep, 1)
            uid, pw = uid.strip(), pw.strip()
            if not uid or not pw or uid in seen:
                continue
            seen.add(uid)
            accounts.append((uid, pw))
    return accounts


def load_done_uids():
    if not RESUME or not os.path.exists(DONE_FILE):
        return set()
    with open(DONE_FILE, "r", encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def save_done_uid(uid):
    with open(DONE_FILE, "a", encoding="utf-8") as f:
        f.write(uid + "\n")


def pick_api():
    global api_rr_index
    while True:
        with lock:
            now = time.time()
            alive = [u for u in APIS if api_stats[u]["cooldown_until"] <= now]
            if alive:
                api_rr_index = (api_rr_index + 1) % len(alive)
                return alive[api_rr_index]
            soonest = min(api_stats[u]["cooldown_until"] for u in APIS)
            wait = soonest - now
        if wait > 0:
            time.sleep(min(wait, 1.0))


def note_api_result(api, success):
    with lock:
        s = api_stats[api]
        if success:
            s["ok"] += 1
            s["consec_errors"] = 0
        else:
            s["fail"] += 1
            s["consec_errors"] += 1
            if s["consec_errors"] >= ERROR_THRESHOLD:
                s["cooldown_until"] = time.time() + COOLDOWN
                print(f"    ⏸  API {api[:55]} lỗi {s['consec_errors']} lần → loại {COOLDOWN:.0f}s")
                s["consec_errors"] = 0


def extract_token(data):
    if not isinstance(data, dict):
        return None
    for key in ("jwt_token", "token", "access_token"):
        v = data.get(key)
        if isinstance(v, str) and v.strip().startswith("eyJ"):
            return v.strip()
    v = data.get("access_token")
    if isinstance(v, str) and len(v.strip()) >= 32:
        return v.strip()
    return None


def call_api(api, uid, password):
    try:
        r = requests.get(
            api,
            params={"uid": uid, "password": password},
            timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except requests.exceptions.Timeout:
        return None, "timeout", True
    except requests.exceptions.RequestException as e:
        return None, f"request_error: {str(e)[:80]}", True

    if r.status_code in (429, 500, 502, 503, 504):
        return None, f"http_{r.status_code}", True

    if r.status_code != 200:
        return None, f"http_{r.status_code}", False

    try:
        data = r.json()
    except ValueError:
        return None, "json_error", True

    token = extract_token(data)
    if not token:
        return None, "no_token", False

    return token, None, False


def get_token(uid, password):
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        api = pick_api()
        token, err, retryable = call_api(api, uid, password)

        if token:
            note_api_result(api, True)
            return token, None

        last_err = err
        note_api_result(api, False)

        if not retryable:
            return None, err

        if attempt < MAX_RETRY:
            time.sleep(RETRY_WAIT * attempt)

    return None, f"retry_failed: {last_err}"


def main():
    print("=" * 60)
    print(f"  GET TOKEN - {len(APIS)} API, {MAX_WORKERS} luồng, RESUME={RESUME}")
    print("=" * 60)
    for i, api in enumerate(APIS, 1):
        print(f"  [{i}] {api}")
    print("-" * 60)

    accounts = load_accounts(INPUT_FILE)
    done = load_done_uids()
    todo = [(u, p) for (u, p) in accounts if u not in done]

    print(f"[+] Tổng acc    : {len(accounts)}")
    print(f"[+] Đã có token : {len(done)}")
    print(f"[+] Cần chạy    : {len(todo)}")
    print("-" * 60)

    if not todo:
        print("[+] Không có gì để chạy.")
        return

    ok = fail = 0
    done_count = 0
    start = time.time()
    write_lock = threading.Lock()

    with open(OUTPUT_FILE, "a", encoding="utf-8") as fout, \
         open(ERROR_FILE, "a", encoding="utf-8") as ferr:

        def handle_result(uid, token, err):
            nonlocal ok, fail, done_count
            with write_lock:
                done_count += 1
                if token:
                    fout.write(token + "\n")
                    fout.flush()
                    save_done_uid(uid)
                    ok += 1
                    status = "OK "
                else:
                    ferr.write(f"{uid}|{err}\n")
                    ferr.flush()
                    fail += 1
                    status = "LỖI"

                elapsed = time.time() - start
                speed = done_count / elapsed if elapsed > 0 else 0
                remain = (len(todo) - done_count) / speed if speed > 0 else 0
                print(f"[{done_count}/{len(todo)}] {status} {uid}  "
                      f"({speed:.1f} acc/s, còn ~{remain:.0f}s)")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(get_token, u, p): u for (u, p) in todo}
            for fut in as_completed(futures):
                uid = futures[fut]
                try:
                    token, err = fut.result()
                except Exception as e:
                    token, err = None, f"exception: {str(e)[:80]}"
                handle_result(uid, token, err)
                time.sleep(DELAY)

    elapsed = time.time() - start
    print("-" * 60)
    print(f"[+] Hoàn tất sau {elapsed:.1f}s")
    print(f"[+] Thành công : {ok}")
    print(f"[+] Lỗi        : {fail}")
    print("-" * 60)
    print("[+] Thống kê API:")
    for api in APIS:
        s = api_stats[api]
        total = s["ok"] + s["fail"]
        rate = (s["ok"] / total * 100) if total > 0 else 0
        print(f"    {api[:55]}  OK={s['ok']}  FAIL={s['fail']}  ({rate:.0f}%)")
    print(f"\n[+] Token   : {OUTPUT_FILE}")
    print(f"[+] Log lỗi : {ERROR_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Dừng. Token đã lưu được giữ nguyên.")
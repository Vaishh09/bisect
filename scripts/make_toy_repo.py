"""Build a REAL toy git repo with MULTIPLE services and MULTIPLE planted bugs,
each surrounded by benign decoys that touch the same files.

This richer history is what makes the hard benchmark credible: every scenario has
a known-bad commit AND several plausible same-file / same-service distractors, so
ranking by timing + blast-radius alone is not enough. You have to read the diffs.

Services: checkout, payments, auth.
Planted bugs (ground truth), each with decoys touching the same file:
  - checkout: removes null-session guard        -> AttributeError NoneType session
  - payments: wrong currency division by zero    -> ZeroDivisionError
  - auth:     drops token-expiry check           -> KeyError 'exp'
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "data" / "toy_repo"

def run(*a, cwd=REPO):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

def write(rel, content):
    p = REPO / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

def commit(msg, author):
    run("git", "add", "-A")
    subprocess.run(["git", "commit", "-m", msg, "--author", f"{author} <{author}@ex.com>"],
                   cwd=REPO, check=True, capture_output=True, text=True)
    return run("git", "rev-parse", "HEAD")

def main():
    if REPO.exists():
        import shutil; shutil.rmtree(REPO)
    REPO.mkdir(parents=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "bot@bisect.dev")
    run("git", "config", "user.name", "bisect-bot")
    s = {}

    # ---------- initial healthy services ----------
    write("checkout/service.py", '''\
"""Checkout service."""


def process_checkout(user, cart):
    if user.session is None:
        raise ValueError("no active session")
    total = sum(i.price for i in cart.items)
    return {"user_id": user.id, "session": user.session.id, "total": total}
''')
    write("payments/service.py", '''\
"""Payments service."""


def charge(amount_cents, rate):
    if rate <= 0:
        raise ValueError("bad rate")
    converted = amount_cents / rate
    return round(converted, 2)
''')
    write("auth/service.py", '''\
"""Auth service."""

import time


def verify(token):
    if "exp" not in token:
        raise ValueError("missing expiry")
    if token["exp"] < time.time():
        raise ValueError("expired")
    return token["sub"]
''')
    s["init"] = commit("feat: initial services", "priya")

    # ---------- benign churn (distractors, various services) ----------
    write("docs/README.md", "# Services\n")
    s["docs"] = commit("docs: add readme", "arjun")

    write("checkout/service.py", REPO.joinpath("checkout/service.py").read_text().replace(
        '"""Checkout service."""', '"""Checkout service."""\nimport logging\nlog = logging.getLogger("checkout")'))
    s["co_log"] = commit("chore: add logging to checkout", "priya")

    write("payments/service.py", REPO.joinpath("payments/service.py").read_text().replace(
        '"""Payments service."""', '"""Payments service."""\nimport logging\nlog = logging.getLogger("pay")'))
    s["pay_log"] = commit("chore: add logging to payments", "sam")

    # ---------- BUG 1: checkout null-session ----------
    write("checkout/service.py", '''\
"""Checkout service."""
import logging
log = logging.getLogger("checkout")


def process_checkout(user, cart):
    total = sum(i.price for i in cart.items)
    return {"user_id": user.id, "session": user.session.id, "total": total}
''')
    s["BUG_checkout"] = commit("refactor: simplify checkout flow", "devuser")

    # decoy touching checkout right after (benign, same file)
    write("checkout/service.py", REPO.joinpath("checkout/service.py").read_text().replace(
        "    total = sum(i.price for i in cart.items)",
        "    # NOTE: hot path, keep fast\n    total = sum(i.price for i in cart.items)"))
    s["co_decoy"] = commit("style: comment checkout hot path", "arjun")

    # ---------- BUG 2: payments divide-by-zero ----------
    write("payments/service.py", '''\
"""Payments service."""
import logging
log = logging.getLogger("pay")


def charge(amount_cents, rate):
    converted = amount_cents / rate
    return round(converted, 2)
''')
    s["BUG_payments"] = commit("refactor: streamline charge()", "devuser")

    # decoy touching payments (benign rename of local var)
    write("payments/service.py", REPO.joinpath("payments/service.py").read_text().replace(
        "converted = amount_cents / rate", "converted = amount_cents / rate  # cents -> currency"))
    s["pay_decoy"] = commit("style: annotate charge()", "sam")

    # ---------- BUG 3: auth drops expiry check ----------
    write("auth/service.py", '''\
"""Auth service."""

import time


def verify(token):
    return token["sub"]
''')
    s["BUG_auth"] = commit("refactor: simplify token verify", "devuser")

    # decoy touching auth (benign)
    write("auth/service.py", REPO.joinpath("auth/service.py").read_text().replace(
        "    return token[\"sub\"]", "    # trusted upstream sets sub\n    return token[\"sub\"]"))
    s["auth_decoy"] = commit("style: note auth trust boundary", "arjun")

    # trailing benign churn
    write("docs/README.md", "# Services\n\nCheckout, payments, auth.\n")
    s["docs2"] = commit("docs: expand readme", "arjun")

    gt = {
        "all_commits": s,
        "bugs": {
            "checkout": {"sha": s["BUG_checkout"], "file": "checkout/service.py",
                         "exception": "AttributeError: 'NoneType' object has no attribute 'id'",
                         "endpoint": "/api/checkout",
                         "decoys": [s["co_decoy"], s["co_log"]]},
            "payments": {"sha": s["BUG_payments"], "file": "payments/service.py",
                         "exception": "ZeroDivisionError: division by zero",
                         "endpoint": "/api/charge",
                         "decoys": [s["pay_decoy"], s["pay_log"]]},
            "auth": {"sha": s["BUG_auth"], "file": "auth/service.py",
                     "exception": "KeyError: 'exp'",
                     "endpoint": "/api/verify",
                     "decoys": [s["auth_decoy"]]},
        },
        # kept for backward compat with older scripts
        "bad_commit_sha": s["BUG_checkout"],
        "decoy_commit_sha": s["co_decoy"],
    }
    (REPO / "GROUND_TRUTH.json").write_text(json.dumps(gt, indent=2))
    print("Toy repo created with", len(s), "commits across 3 services.")
    print(run("git", "log", "--oneline", "--pretty=format:%h  %an  %s"))
    print("\nPlanted bugs:")
    for name, b in gt["bugs"].items():
        print(f"  {name:9} bad={b['sha'][:8]}  decoys={[d[:8] for d in b['decoys']]}")

if __name__ == "__main__":
    main()

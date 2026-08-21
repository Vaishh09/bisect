"""Build a REAL toy git repo (a 'checkout service') with a planted bad commit.
The bad commit removes a null-session guard; that sha is our ground truth."""
from __future__ import annotations
import json, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "data" / "toy_repo"

def run(*args, cwd=REPO):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

def write(rel, content):
    p = REPO / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)

def commit(message, author):
    run("git", "add", "-A")
    subprocess.run(["git", "commit", "-m", message, "--author", f"{author} <{author}@example.com>"],
                   cwd=REPO, check=True, capture_output=True, text=True)
    return run("git", "rev-parse", "HEAD")

def main():
    if REPO.exists():
        import shutil; shutil.rmtree(REPO)
    REPO.mkdir(parents=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "bot@bisect.dev")
    run("git", "config", "user.name", "bisect-bot")
    shas = {}

    write("checkout/service.py", '''\
"""Checkout service."""


def process_checkout(user, cart):
    if user.session is None:
        raise ValueError("no active session")
    total = sum(item.price for item in cart.items)
    return {"user_id": user.id, "session": user.session.id, "total": total}
''')
    write("checkout/models.py", '''\
class Session:
    def __init__(self, id): self.id = id
class User:
    def __init__(self, id, session): self.id = id; self.session = session
class Item:
    def __init__(self, price): self.price = price
class Cart:
    def __init__(self, items): self.items = items
''')
    shas["init_checkout"] = commit("feat: initial checkout service", "priya")

    write("docs/README.md", "# Checkout Service\n\nHandles order processing.\n")
    shas["docs"] = commit("docs: add service README", "arjun")

    write("checkout/service.py", '''\
"""Checkout service."""
import logging
log = logging.getLogger("checkout")


def process_checkout(user, cart):
    if user.session is None:
        raise ValueError("no active session")
    log.info("processing checkout for user %s", user.id)
    total = sum(item.price for item in cart.items)
    return {"user_id": user.id, "session": user.session.id, "total": total}
''')
    shas["logging"] = commit("chore: add logging to checkout", "priya")

    # THE BAD COMMIT — removes the null-session guard
    write("checkout/service.py", '''\
"""Checkout service."""
import logging
log = logging.getLogger("checkout")


def process_checkout(user, cart):
    log.info("processing checkout for user %s", user.id)
    total = sum(item.price for item in cart.items)
    return {"user_id": user.id, "session": user.session.id, "total": total}
''')
    shas["BAD"] = commit("refactor: simplify checkout flow", "devuser")

    write("checkout/models.py", REPO.joinpath("checkout/models.py").read_text()
          + '\nclass Coupon:\n    def __init__(self, code): self.code = code\n')
    shas["coupon"] = commit("feat: add coupon model", "arjun")

    gt = {"bad_commit_sha": shas["BAD"],
          "bad_commit_reason": "Removed the null-session guard in checkout/service.py; "
                               "users without a session hit AttributeError on NoneType.",
          "all_commits": shas}
    (REPO / "GROUND_TRUTH.json").write_text(json.dumps(gt, indent=2))
    print("Toy repo created at:", REPO)
    print(run("git", "log", "--oneline", "--pretty=format:%h  %an  %s"))
    print("\nPlanted bad commit:", shas["BAD"][:8])

if __name__ == "__main__":
    main()

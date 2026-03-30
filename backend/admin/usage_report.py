"""
Usage report: show per-user token consumption.

Run from the backend/ directory:
    python admin/usage_report.py              # all users
    python admin/usage_report.py --days 30   # last N days
    python admin/usage_report.py --user bob  # specific user
"""
import sys
import argparse
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ignore unrelated shell DEBUG values (for example "release" from an IDE env)
# so Pydantic can read the boolean DEBUG setting from backend/.env.
os.environ.pop("DEBUG", None)

import logging
logging.disable(logging.CRITICAL)  # suppress all library noise

from core.database import SessionLocal
from models.database import TokenUsage, User, GuestTokenUsage


def report(days: int | None = None, username: str | None = None):
    db = SessionLocal()
    try:
        since = time.time() - days * 86400 if days else 0

        users = db.query(User).order_by(User.created_at).all()
        if username:
            users = [u for u in users if u.username == username]
            if not users:
                print(f"User '{username}' not found.")
                return

        print(f"\n{'─'*72}")
        header = "USERNAME" if not days else f"USERNAME (last {days}d)"
        print(f"  {header:<24} {'QUERIES':>8}  {'INPUT':>10}  {'OUTPUT':>10}  {'TOTAL':>10}")
        print(f"{'─'*72}")

        from collections import defaultdict
        import datetime

        grand = {"q": 0, "in": 0, "out": 0}
        for user in users:
            q = db.query(TokenUsage).filter(TokenUsage.user_id == user.id)
            if since:
                q = q.filter(TokenUsage.timestamp >= since)
            rows = q.all()

            n = len(rows)
            in_tok = sum(r.input_tokens for r in rows)
            out_tok = sum(r.output_tokens for r in rows)
            total = in_tok + out_tok

            grand["q"] += n
            grand["in"] += in_tok
            grand["out"] += out_tok

            active = "" if user.is_active else " (inactive)"
            print(f"  {user.username + active:<24} {n:>8}  {in_tok:>10,}  {out_tok:>10,}  {total:>10,}")

            # Per-model breakdown under each user
            by_model: dict = defaultdict(lambda: {"q": 0, "in": 0, "out": 0})
            for r in rows:
                key = r.model or "unknown"
                by_model[key]["q"] += 1
                by_model[key]["in"] += r.input_tokens
                by_model[key]["out"] += r.output_tokens
            if len(by_model) > 1 or (len(by_model) == 1 and list(by_model.keys())[0] != "unknown"):
                for model_name in sorted(by_model):
                    m = by_model[model_name]
                    print(f"    {'↳ ' + model_name:<26} {m['q']:>8}  {m['in']:>10,}  {m['out']:>10,}  {m['in']+m['out']:>10,}")

        print(f"{'─'*72}")
        grand_total = grand["in"] + grand["out"]
        print(f"  {'TOTAL':<24} {grand['q']:>8}  {grand['in']:>10,}  {grand['out']:>10,}  {grand_total:>10,}")
        print(f"{'─'*72}\n")

        # ── Guest usage section ───────────────────────────────────────────────
        guest_q = db.query(GuestTokenUsage)
        if since:
            guest_q = guest_q.filter(GuestTokenUsage.timestamp >= since)
        guest_rows = guest_q.order_by(GuestTokenUsage.timestamp).all()

        if guest_rows:
            print(f"{'─'*72}")
            print(f"  GUEST USAGE (by IP){'':<5} {'QUERIES':>8}  {'INPUT':>10}  {'OUTPUT':>10}  {'TOTAL':>10}")
            print(f"{'─'*72}")

            by_ip: dict = defaultdict(lambda: {"q": 0, "in": 0, "out": 0})
            for r in guest_rows:
                by_ip[r.ip_address]["q"] += 1
                by_ip[r.ip_address]["in"] += r.input_tokens
                by_ip[r.ip_address]["out"] += r.output_tokens

            g_grand = {"q": 0, "in": 0, "out": 0}
            for ip_addr in sorted(by_ip):
                g = by_ip[ip_addr]
                print(f"  {ip_addr:<24} {g['q']:>8}  {g['in']:>10,}  {g['out']:>10,}  {g['in']+g['out']:>10,}")
                g_grand["q"] += g["q"]
                g_grand["in"] += g["in"]
                g_grand["out"] += g["out"]

            print(f"{'─'*72}")
            g_total = g_grand["in"] + g_grand["out"]
            print(f"  {'GUEST TOTAL':<24} {g_grand['q']:>8}  {g_grand['in']:>10,}  {g_grand['out']:>10,}  {g_total:>10,}")
            print(f"{'─'*72}\n")
        else:
            print("  No guest token usage recorded.\n")

        if users and len(users) == 1:
            # Show monthly breakdown for single-user view
            user = users[0]
            rows = db.query(TokenUsage).filter(TokenUsage.user_id == user.id).order_by(TokenUsage.timestamp).all()
            if rows:
                monthly: dict = defaultdict(lambda: {"q": 0, "in": 0, "out": 0})
                monthly_models: dict = defaultdict(lambda: defaultdict(lambda: {"q": 0, "in": 0, "out": 0}))
                for r in rows:
                    month = datetime.datetime.fromtimestamp(r.timestamp).strftime("%Y-%m")
                    monthly[month]["q"] += 1
                    monthly[month]["in"] += r.input_tokens
                    monthly[month]["out"] += r.output_tokens
                    monthly_models[month][r.model or "unknown"]["q"] += 1
                    monthly_models[month][r.model or "unknown"]["in"] += r.input_tokens
                    monthly_models[month][r.model or "unknown"]["out"] += r.output_tokens

                print(f"  Monthly breakdown for {user.username}:")
                print(f"  {'MONTH':<12} {'QUERIES':>8}  {'INPUT':>10}  {'OUTPUT':>10}  {'TOTAL':>10}")
                print(f"  {'─'*58}")
                for month in sorted(monthly):
                    m = monthly[month]
                    print(f"  {month:<12} {m['q']:>8}  {m['in']:>10,}  {m['out']:>10,}  {m['in']+m['out']:>10,}")
                    models_in_month = monthly_models[month]
                    if len(models_in_month) > 1 or list(models_in_month.keys())[0] != "unknown":
                        for model_name in sorted(models_in_month):
                            mm = models_in_month[model_name]
                            print(f"    {'↳ ' + model_name:<14} {mm['q']:>8}  {mm['in']:>10,}  {mm['out']:>10,}  {mm['in']+mm['out']:>10,}")
                print()

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedOmicsChat usage report")
    parser.add_argument("--days", type=int, default=None, help="Limit to last N days")
    parser.add_argument("--user", type=str, default=None, help="Filter to a specific username")
    args = parser.parse_args()
    report(days=args.days, username=args.user)

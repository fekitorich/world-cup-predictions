"""Execute the bet plan on Polymarket (CLOB API).

  .venv/bin/python3 betting/place_bets.py           # DRY RUN (default)
  .venv/bin/python3 betting/place_bets.py --live    # places real orders

Safety rails, all enforced here regardless of what the plan says:
  - hard refuse if total placed (ledger) + new stakes > max_total_stake_usdc
  - hard refuse any single stake > max_per_bet_usdc
  - never re-places a token_id already in the ledger
  - dry run is the default; --live is required to spend money

Secrets: put your Polygon wallet private key in betting/.env (gitignored):
  POLYMARKET_PRIVATE_KEY=0x...
  POLYMARKET_FUNDER=0x...        # only for email/Magic accounts (proxy wallet)
Your wallet needs USDC on Polygon with Polymarket allowances already set
(easiest: deposit + one manual trade via the UI first).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(f"{HERE}/config.json"))
LEDGER_PATH = f"{HERE}/state/ledger.json"


def load_env():
    env = {}
    path = f"{HERE}/.env"
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items()
                if k.startswith("POLYMARKET_")})
    return env


def load_ledger():
    if os.path.exists(LEDGER_PATH):
        return json.load(open(LEDGER_PATH))
    return {"placed": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually place orders (default: dry run)")
    args = ap.parse_args()

    plan = json.load(open(f"{HERE}/state/plan.json"))
    ledger = load_ledger()
    spent = sum(b["stake_usdc"] for b in ledger["placed"])
    done_tokens = {b["token_id"] for b in ledger["placed"]}

    todo = []
    for b in plan["bets"]:
        if b["token_id"] in done_tokens:
            print(f"skip (already placed): {b['bet']}")
            continue
        if b["stake_usdc"] < 1:
            continue
        if b["stake_usdc"] > CFG["max_per_bet_usdc"]:
            print(f"REFUSE (> per-bet cap): {b['bet']} ${b['stake_usdc']}")
            continue
        if spent + sum(t["stake_usdc"] for t in todo) + b["stake_usdc"] \
                > CFG["max_total_stake_usdc"]:
            print(f"REFUSE (would exceed total cap): {b['bet']}")
            continue
        todo.append(b)

    batch = sum(b["stake_usdc"] for b in todo)
    print(f"\nledger so far: ${spent:.2f} · this batch: ${batch:.2f} "
          f"· cap: ${CFG['max_total_stake_usdc']}")
    if not todo:
        print("nothing to place")
        return

    if not args.live:
        print("\nDRY RUN — would place:")
        for b in todo:
            print(f"  BUY ${b['stake_usdc']:>6.2f} YES @ ~{b['market_p']:.2f}  {b['bet']}")
        print("\nre-run with --live to place for real")
        return

    env = load_env()
    key = env.get("POLYMARKET_PRIVATE_KEY")
    if not key:
        sys.exit("POLYMARKET_PRIVATE_KEY missing — put it in betting/.env "
                 "(gitignored) or the environment")

    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import MarketOrderArgs, OrderType

    funder = env.get("POLYMARKET_FUNDER")
    if funder:   # email/Magic login accounts trade through a proxy wallet
        client = ClobClient("https://clob.polymarket.com", key=key,
                            chain_id=137, signature_type=1, funder=funder)
    else:        # plain EOA wallet
        client = ClobClient("https://clob.polymarket.com", key=key, chain_id=137)
    client.set_api_creds(client.create_or_derive_api_creds())

    for b in todo:
        print(f"placing ${b['stake_usdc']:.2f} on {b['bet']} ...", flush=True)
        try:
            order = client.create_market_order(MarketOrderArgs(
                token_id=b["token_id"], amount=b["stake_usdc"], side="BUY"))
            resp = client.post_order(order, OrderType.FOK)
            ok = bool(resp and resp.get("success"))
            print("  ->", resp)
        except Exception as e:
            print(f"  FAILED: {e}")
            ok = False
        if ok:
            ledger["placed"].append({
                "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                "bet": b["bet"], "token_id": b["token_id"],
                "stake_usdc": b["stake_usdc"], "price_seen": b["market_p"],
                "model_p": b["model_p"], "category": b["category"],
            })
            json.dump(ledger, open(LEDGER_PATH, "w"), indent=2)
        time.sleep(1)

    total = sum(x["stake_usdc"] for x in ledger["placed"])
    print(f"\nledger total now ${total:.2f} / ${CFG['max_total_stake_usdc']} cap "
          f"({LEDGER_PATH})")


if __name__ == "__main__":
    main()

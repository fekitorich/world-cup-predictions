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
if os.path.exists(f"{HERE}/config.local.json"):   # gitignored personal caps
    CFG.update(json.load(open(f"{HERE}/config.local.json")))
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
    ap.add_argument("--limit", type=int, default=None,
                    help="place at most N orders from the top of the plan")
    args = ap.parse_args()

    plan = json.load(open(f"{HERE}/state/plan.json"))
    ledger = load_ledger()
    spent = sum(b["stake_usdc"] for b in ledger["placed"])
    done_tokens = {b["token_id"] for b in ledger["placed"]}
    # market-level dedup: never touch a market we already hold a side of —
    # buying the complementary token of an earlier bet locks in a loss
    done_markets = {b["question"] for b in ledger["placed"] if b.get("question")}

    todo = []
    for b in plan["bets"]:
        if b["token_id"] in done_tokens:
            print(f"skip (already placed): {b['bet']}")
            continue
        if b.get("question") and b["question"] in done_markets:
            print(f"skip (market already held, other side?): {b['bet']}")
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

    if args.limit:
        todo = todo[:args.limit]
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

    # V2 SDK — required since Polymarket's 2026-04-28 exchange migration
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import (ApiCreds, MarketOrderArgsV2,
                                              OrderType,
                                              PartialCreateOrderOptions)

    funder = env.get("POLYMARKET_FUNDER")
    # 1 = email/Magic login, 2 = MetaMask/browser-wallet login
    sig_type = int(env.get("POLYMARKET_SIGNATURE_TYPE", "1"))
    if funder:   # normal Polymarket accounts trade through a proxy wallet
        client = ClobClient("https://clob.polymarket.com", key=key,
                            chain_id=137, signature_type=sig_type, funder=funder)
    else:        # plain EOA trading directly (rare)
        client = ClobClient("https://clob.polymarket.com", key=key, chain_id=137)
    # derive CLOB creds from the signing key (canonical path); fall back to
    # any explicitly provided creds if derivation fails
    try:
        client.set_api_creds(client.create_or_derive_api_key())
    except Exception as e:
        if env.get("CLOB_API_KEY"):
            print(f"derive failed ({e}); trying provided CLOB creds")
            client.set_api_creds(ApiCreds(
                api_key=env["CLOB_API_KEY"], api_secret=env["CLOB_SECRET"],
                api_passphrase=env["CLOB_PASSPHRASE"]))
        else:
            raise

    for b in todo:
        print(f"placing ${b['stake_usdc']:.2f} on {b['bet']} ...", flush=True)
        try:
            # WC match markets are neg-risk (multi-outcome) markets
            order = client.create_market_order(
                MarketOrderArgsV2(token_id=b["token_id"],
                                  amount=b["stake_usdc"], side="BUY"),
                PartialCreateOrderOptions(neg_risk=True))
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
                "question": b.get("question", ""),
                "match_id": b.get("match_id", ""),
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

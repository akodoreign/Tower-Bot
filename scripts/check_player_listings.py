import sys
import json
from dotenv import load_dotenv
load_dotenv()
from src.db_api import raw_query

rows = raw_query("SELECT id, player_id, player_name, item_name, asking_price, status, listing_json FROM player_listings ORDER BY id")
print(f"Total rows: {len(rows)}")

issues = []

for r in rows:
    row_id = r["id"]
    status = r.get("status", "")
    lj = r.get("listing_json") or ""

    # Check JSON parseable
    json_ok = True
    parsed = None
    if lj:
        try:
            parsed = json.loads(lj)
        except Exception as e:
            json_ok = False
            issues.append(f"id={row_id}: listing_json is invalid JSON: {e}")

    # Check required fields in parsed blob
    if parsed:
        for field in ("item_name", "player_id", "status", "expires_at"):
            if field not in parsed:
                issues.append(f"id={row_id}: listing_json missing field '{field}'")

    # Check status value
    if status not in ("active", "sold", "unsold", "expired", ""):
        issues.append(f"id={row_id}: unexpected status value '{status}'")

    # Check asking_price
    price = r.get("asking_price")
    if price is None or price < 0:
        issues.append(f"id={row_id}: bad asking_price={price}")

    # Check player_id not empty
    if not r.get("player_id"):
        issues.append(f"id={row_id}: empty player_id")

    print(
        f"  id={row_id:3}  player={str(r.get('player_name',''))[:20]:<20}  "
        f"item={str(r.get('item_name',''))[:30]:<30}  "
        f"status={status:<8}  price={price}  json={'OK' if json_ok else 'BAD'}"
    )

print()
if issues:
    print(f"ISSUES FOUND ({len(issues)}):")
    for issue in issues:
        print(f"  {issue}")
else:
    print("No issues found.")

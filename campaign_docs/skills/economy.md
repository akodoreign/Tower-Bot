# Skill: Undercity Economy
**Keywords:** economy, gold, kharma, EC, currency, towerbay, auction, TIA, stock, market, prices, exchange, trade, buy, sell, shop
**Category:** systems
**Version:** 1
**Source:** seed

## Currencies

The Undercity uses multiple currencies:

- **Gold (gp)** — Standard D&D currency, used for mundane purchases.
- **EC (Energy Credits)** — The Undercity's digital currency. Used for higher-end transactions, faction services, and TowerBay auctions.
- **Kharma** — A reputation-based currency earned through missions, downtime, and faction service. Can be exchanged for EC at a fluctuating rate.

## EC/Kharma Exchange

The exchange rate between EC and Kharma fluctuates like a real market. The `ec_exchange.json` file tracks the current rate. Players can check the rate with `/finances`.

## TowerBay Auction House

TowerBay is the Undercity's auction house where players and NPCs list items for sale. Players use `/towerbay` to view current listings and `/myauctions` to manage their own.

## TIA (Tower Investment Authority)

The TIA tracks a simulated stock market with sectors like Mining, Arcane Research, Trade, etc. Sector values fluctuate based on news events — a rift spike might crash Arcane Research stocks while boosting Military sector. TIA flash bulletins report significant market moves.

## Prices

The `/prices` command shows current market prices for common goods and services. Prices fluctuate based on supply, demand, and world events.

## How Players Earn Money
- Completing missions (gold + Kharma rewards)
- Selling items on TowerBay
- Faction contracts and downtime activities
- Arena victories
- Bounty hunting

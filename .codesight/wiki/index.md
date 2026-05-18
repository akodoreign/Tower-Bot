# chatgpt-discord-bot — Wiki

_Generated 2026-05-17 — re-run `npx codesight --wiki` if the codebase has changed._

Structural map compiled from source code via AST. No LLM — deterministic, 200ms.

> **How to use safely:** These articles tell you WHERE things live and WHAT exists. They do not show full implementation logic. Always read the actual source files before implementing new features or making changes. Never infer how a function works from the wiki alone.

## Articles

- [Overview](./overview.md)
- [Database](./database.md)
- [Area-maps](./area-maps.md)
- [Arena](./arena.md)
- [Bounties](./bounties.md)
- [Bulletins](./bulletins.md)
- [Claim-mission](./claim-mission.md)
- [Compendium](./compendium.md)
- [Complete-mission](./complete-mission.md)
- [Districts](./districts.md)
- [Drafts](./drafts.md)
- [Factions](./factions.md)
- [Generate-mission](./generate-mission.md)
- [Image-refs](./image-refs.md)
- [Log-bug](./log-bug.md)
- [Logs](./logs.md)
- [Media](./media.md)
- [Mission-maps](./mission-maps.md)
- [Mission-types](./mission-types.md)
- [Missions](./missions.md)
- [Modules](./modules.md)
- [Npcs](./npcs.md)
- [Parties](./parties.md)
- [Places](./places.md)
- [Portraits](./portraits.md)
- [Post-mission-to-discord](./post-mission-to-discord.md)
- [Print](./print.md)
- [Status](./status.md)
- [View-mode](./view-mode.md)
- [Infra](./infra.md)
- [Libraries](./libraries.md)

## Quick Stats

- Routes: **38**
- Models: **15**
- Components: **0**
- Env vars: **78** required, **59** with defaults

## How to Use

- **New session:** read `index.md` (this file) for orientation — WHERE things are
- **Architecture question:** read `overview.md` (~500 tokens)
- **Domain question:** read the relevant article, then **read those source files**
- **Database question:** read `database.md`, then read the actual schema files
- **Library question:** read `libraries.md`, then read the listed source files
- **Before implementing anything:** read the source files listed in the article
- **Full source context:** read `.codesight/CODESIGHT.md`

## What the Wiki Does Not Cover

These exist in your codebase but are **not** reflected in wiki articles:
- Routes registered dynamically at runtime (loops, plugin factories, `app.use(dynamicRouter)`)
- Internal routes from npm packages (e.g. Better Auth's built-in `/api/auth/*` endpoints)
- WebSocket and SSE handlers
- Raw SQL tables not declared through an ORM
- Computed or virtual fields absent from schema declarations
- TypeScript types that are not actual database columns
- Routes marked `[inferred]` were detected via regex and may have lower precision
- gRPC, tRPC, and GraphQL resolvers may be partially captured

When in doubt, search the source. The wiki is a starting point, not a complete inventory.

---
_Last compiled: 2026-05-17 · 32 articles · [codesight](https://github.com/Houseofmvps/codesight)_
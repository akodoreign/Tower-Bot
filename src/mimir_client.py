"""
mimir_client.py — Async MCP client for Mimir DM.

Spawns mimir-mcp as a stdio subprocess and wraps its tools.
All calls fail silently when Mimir is unavailable — zero impact on
existing pipeline behavior.

Configuration (.env):
    MIMIR_MCP_PATH      — path to mimir-mcp binary
    MIMIR_CAMPAIGN_ID   — active campaign UUID (set after opening Mimir)
"""

from __future__ import annotations

import os
import json
import asyncio
from pathlib import Path
from typing import Any, Optional

from src.log import logger

MIMIR_MCP_PATH      = os.getenv("MIMIR_MCP_PATH", "")
MIMIR_CAMPAIGN_ID   = os.getenv("MIMIR_CAMPAIGN_ID", "")
MIMIR_CAMPAIGN_NAME = os.getenv("MIMIR_CAMPAIGN_NAME", "Tower of Last Chance")


_RECONNECT_COOLDOWN  = 300   # seconds before retrying after all attempts exhausted
_RECONNECT_ATTEMPTS  = 3     # how many times to try before entering cooldown
_RECONNECT_DELAY     = 30    # seconds between attempts

_CANCEL_SCOPE_TASK_MISMATCH = "Attempted to exit cancel scope in a different task"


def _is_expected_stdio_shutdown_noise(exc: BaseException) -> bool:
    """Return True for the known anyio stdio_client shutdown BaseExceptionGroup."""
    if isinstance(exc, RuntimeError):
        return _CANCEL_SCOPE_TASK_MISMATCH in str(exc)
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return bool(exc.exceptions) and all(
            _is_expected_stdio_shutdown_noise(sub_exc) for sub_exc in exc.exceptions
        )
    return False


class MimirClient:
    """Singleton async MCP client for Mimir DM."""

    def __init__(self) -> None:
        self._available        = False
        self._session          = None
        self._stdio_ctx        = None
        self._errlog_handle    = None
        self._lock             = asyncio.Lock()
        self._reconnect_lock   = asyncio.Lock()
        self._campaign_id      = ""
        self._last_failed_at   = 0.0   # epoch time of last exhausted reconnect attempt
        self._reconnecting     = False  # guard against concurrent reconnect calls

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_connected(self) -> bool:
        """
        Call before any pipeline use.  If already connected, returns True immediately.
        If disconnected, attempts to (re)spawn mimir-mcp up to _RECONNECT_ATTEMPTS times
        with _RECONNECT_DELAY seconds between tries, then enters a _RECONNECT_COOLDOWN
        backoff so crashed subprocesses are not hammered.

        Safe to call concurrently — only one reconnect runs at a time.
        """
        if self._available:
            return True
        if not MIMIR_MCP_PATH:
            return False

        import time
        async with self._reconnect_lock:
            # Re-check under lock — another coroutine may have connected while we waited
            if self._available:
                return True
            if self._reconnecting:
                return False

            # Cooldown: if we exhausted retries recently, don't hammer the binary
            if self._last_failed_at and (time.monotonic() - self._last_failed_at) < _RECONNECT_COOLDOWN:
                remaining = int(_RECONNECT_COOLDOWN - (time.monotonic() - self._last_failed_at))
                logger.debug(f"[MIMIR] Reconnect in cooldown — {remaining}s remaining")
                return False

            self._reconnecting = True
            try:
                for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
                    logger.debug(f"[MIMIR] Reconnect attempt {attempt}/{_RECONNECT_ATTEMPTS}…")
                    # Disconnect cleanly before respawning
                    await self.disconnect()
                    ok = await self.connect()
                    if ok:
                        logger.info(f"[MIMIR] Reconnected on attempt {attempt} ✓")
                        self._last_failed_at = 0.0
                        return True
                    if attempt < _RECONNECT_ATTEMPTS:
                        logger.debug(f"[MIMIR] Attempt {attempt} failed — waiting {_RECONNECT_DELAY}s")
                        await asyncio.sleep(_RECONNECT_DELAY)

                # All attempts exhausted
                self._last_failed_at = time.monotonic()
                logger.warning(
                    f"[MIMIR] All {_RECONNECT_ATTEMPTS} reconnect attempts failed — "
                    f"entering {_RECONNECT_COOLDOWN}s cooldown. "
                    f"Check that mimir-mcp.exe is installed at: {MIMIR_MCP_PATH}"
                )
                return False
            finally:
                self._reconnecting = False

    async def connect(self) -> bool:
        """Start mimir-mcp subprocess and initialise the MCP session."""
        if not MIMIR_MCP_PATH:
            logger.debug("[MIMIR] MIMIR_MCP_PATH not set — Mimir integration disabled")
            return False

        binary = Path(MIMIR_MCP_PATH)
        if not binary.exists():
            logger.warning(f"[MIMIR] Binary not found: {binary} — integration disabled")
            return False

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            # Pass database path through environment so mimir-mcp can find the DB
            import copy
            _env = copy.copy(dict(os.environ))
            # Keep mimir-mcp's per-call INFO chatter out of the main bot log.
            # Some builds ignore one of these vars, so set both and redirect
            # child stderr to a sidecar file for debugging noisy subprocesses.
            mimir_log_level = os.getenv("MIMIR_LOG_LEVEL", "warn")
            _env["RUST_LOG"] = os.getenv("RUST_LOG", f"{mimir_log_level},mimir_mcp={mimir_log_level}")
            _env["MIMIR_LOG_LEVEL"] = mimir_log_level
            _db_path = os.getenv("MIMIR_DATABASE_PATH", "")
            if _db_path:
                _env["MIMIR_DATABASE_PATH"] = _db_path
            params = StdioServerParameters(command=str(binary), args=[], env=_env)
            logs_dir = Path(__file__).resolve().parents[1] / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            self._errlog_handle = (logs_dir / "mimir_mcp_stderr.log").open(
                "a", encoding="utf-8", errors="replace"
            )
            self._stdio_ctx = stdio_client(params, errlog=self._errlog_handle)
            read, write = await self._stdio_ctx.__aenter__()

            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()

            self._available = True
            logger.info("[MIMIR] Connected to mimir-mcp ✓")

            # Set campaign: explicit ID wins; otherwise search by name
            campaign_id = MIMIR_CAMPAIGN_ID
            if not campaign_id:
                campaign_id = await self._find_campaign_by_name(MIMIR_CAMPAIGN_NAME)

            if campaign_id:
                r = await self._call("set_active_campaign", campaign_id=campaign_id)
                logger.debug(f"[MIMIR] set_active_campaign({campaign_id}) → {str(r)[:200]}")
                self._campaign_id = campaign_id   # set regardless — mimir-mcp may return null on success
                logger.debug(f"[MIMIR] Active campaign set: {campaign_id}")
            else:
                logger.warning(f"[MIMIR] Campaign '{MIMIR_CAMPAIGN_NAME}' not found — create it in Mimir first")

            return True

        except ImportError:
            logger.error("[MIMIR] mcp package missing — run: pip install mcp")
            if self._errlog_handle:
                try:
                    self._errlog_handle.close()
                except Exception:
                    pass
                self._errlog_handle = None
            return False
        except Exception as exc:
            logger.warning(f"[MIMIR] Connection failed: {exc}")
            if self._errlog_handle:
                try:
                    self._errlog_handle.close()
                except Exception:
                    pass
                self._errlog_handle = None
            return False

    async def _find_campaign_by_name(self, name: str) -> str:
        """Search campaigns for one matching name (case-insensitive). Returns ID or ''."""
        r = await self._call("list_campaigns")
        logger.debug(f"[MIMIR] list_campaigns raw response: {str(r)[:300]}")
        # Response may be a list directly or wrapped in {"campaigns": [...]}
        if isinstance(r, list):
            campaigns = r
        else:
            campaigns = (r or {}).get("campaigns", [])
        logger.debug(f"[MIMIR] Campaigns found: {[(c.get('name','?'), c.get('id','?')) for c in campaigns]}")
        name_lower = name.lower()
        for c in campaigns:
            cname = (c.get("name") or c.get("title") or "").lower()
            cid   = c.get("id") or c.get("campaign_id") or c.get("uuid") or ""
            if cname == name_lower and cid:
                return str(cid)
        for c in campaigns:
            cname = (c.get("name") or c.get("title") or "").lower()
            cid   = c.get("id") or c.get("campaign_id") or c.get("uuid") or ""
            if name_lower in cname and cid:
                return str(cid)
        return ""

    @property
    def campaign_id(self) -> str:
        return self._campaign_id

    async def disconnect(self) -> None:
        session = self._session
        self._session = None
        if session:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
        stdio_ctx = self._stdio_ctx
        self._stdio_ctx = None
        if stdio_ctx:
            try:
                await stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if _is_expected_stdio_shutdown_noise(exc):
                    logger.debug("[MIMIR] Ignored stdio shutdown cancel-scope noise")
                else:
                    raise
        if self._errlog_handle:
            try:
                self._errlog_handle.close()
            except Exception:
                pass
            self._errlog_handle = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Raw call
    # ------------------------------------------------------------------

    async def _call(self, tool: str, **kwargs) -> Optional[Any]:
        if not self._available or not self._session:
            return None
        async with self._lock:
            try:
                result = await self._session.call_tool(tool, kwargs)
                if result and result.content:
                    text_parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            text_parts.append(item.text)
                    if not text_parts:
                        return None
                    if len(text_parts) == 1:
                        try:
                            return json.loads(text_parts[0])
                        except json.JSONDecodeError:
                            return text_parts[0]

                    combined = "\n".join(text_parts)
                    try:
                        return json.loads(combined)
                    except json.JSONDecodeError:
                        pass

                    parsed_parts = []
                    all_json = True
                    for text in text_parts:
                        try:
                            parsed_parts.append(json.loads(text))
                        except json.JSONDecodeError:
                            all_json = False
                            break
                    if all_json:
                        if all(isinstance(part, dict) for part in parsed_parts):
                            merged: dict = {}
                            for part in parsed_parts:
                                merged.update(part)
                            return merged
                        if all(isinstance(part, list) for part in parsed_parts):
                            merged_list = []
                            for part in parsed_parts:
                                merged_list.extend(part)
                            return merged_list
                        return parsed_parts

                    return combined
                return None
            except Exception as exc:
                logger.debug(f"[MIMIR] {tool} failed: {exc}")
                return None

    # ------------------------------------------------------------------
    # Campaign
    # ------------------------------------------------------------------

    async def list_campaigns(self) -> Optional[list]:
        r = await self._call("list_campaigns")
        return (r or {}).get("campaigns", [])

    async def set_campaign(self, campaign_id: str) -> bool:
        r = await self._call("set_active_campaign", campaign_id=campaign_id)
        return bool(r)

    async def create_campaign(self, name: str, description: str = "") -> Optional[dict]:
        r = await self._call("create_campaign", name=name, description=description)
        return (r or {}).get("campaign")

    # ------------------------------------------------------------------
    # Characters (NPCs + PCs)
    # ------------------------------------------------------------------

    async def create_character(
        self,
        name: str,
        character_type: str = "npc",
        race_name: str = "Human",
        class_name: str = "",
        level: int = 1,
    ) -> Optional[dict]:
        kwargs: dict = {"name": name, "character_type": character_type, "race_name": race_name}
        if class_name:
            kwargs["class_name"] = class_name
        if level:
            kwargs["level"] = max(1, int(level))
        r = await self._call("create_character", **kwargs)
        return (r or {}).get("character")

    async def edit_character(self, character_id: str, **kwargs) -> bool:
        r = await self._call("edit_character", character_id=character_id, **kwargs)
        return bool(r)

    async def get_character(self, character_id: str) -> Optional[dict]:
        r = await self._call("get_character", character_id=character_id)
        return (r or {}).get("character", r)

    async def list_characters(
        self,
        character_type: Optional[str] = None,
        location: str = "",
        faction: str = "",
    ) -> list:
        kwargs: dict = {}
        if character_type:
            kwargs["character_type"] = character_type
        if location:
            kwargs["location"] = location
        if faction:
            kwargs["faction"] = faction
        r = await self._call("list_characters", **kwargs)
        return (r or {}).get("characters", [])

    async def delete_character(self, character_id: str) -> bool:
        r = await self._call("delete_character", character_id=character_id)
        return bool(r)

    async def add_item_to_character(
        self,
        character_id: str,
        item_name: str,
        equipped: bool = False,
        quantity: int = 1,
        attuned: bool = False,
    ) -> bool:
        r = await self._call(
            "add_item_to_character",
            character_id=character_id,
            item_name=item_name,
            equipped=equipped,
            quantity=quantity,
            attuned=attuned,
        )
        return bool(r)

    async def add_character_spell(
        self,
        character_id: str,
        spell_name: str,
        source_class: str,
        spell_source: str = "PHB",
        prepared: bool = False,
    ) -> bool:
        r = await self._call(
            "add_character_spell",
            character_id=character_id,
            spell_name=spell_name,
            source_class=source_class,
            spell_source=spell_source,
            prepared=prepared,
        )
        return bool(r)

    async def level_up_character(
        self,
        character_id: str,
        class_name: str,
        hp_method: str = "manual",
        hp_value: int = 0,
    ) -> bool:
        kwargs: dict = {"character_id": character_id, "class_name": class_name, "hp_method": hp_method}
        if hp_value:
            kwargs["hp_value"] = hp_value
        r = await self._call("level_up_character", **kwargs)
        return bool(r)

    # ------------------------------------------------------------------
    # Modules
    # ------------------------------------------------------------------

    async def create_module(
        self,
        name: str,
        description: str = "",
        module_type: str = "Standard Adventure",
    ) -> Optional[dict]:
        kwargs: dict = {"name": name, "description": description}
        if module_type:
            kwargs["type"] = module_type
        r = await self._call("create_module", **kwargs)
        return (r or {}).get("module")

    async def get_module(self, module_id: str) -> Optional[dict]:
        r = await self._call("get_module_details", module_id=module_id)
        return r

    async def delete_module(self, module_id: str) -> bool:
        r = await self._call("delete_module", module_id=module_id)
        return bool(r)

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    async def search_monsters(
        self,
        name: str = "",
        cr_min: float | None = None,
        cr_max: float | None = None,
        creature_type: str = "",
    ) -> list[dict]:
        kwargs: dict = {"category": "monster"}
        if name:
            kwargs["name"] = name
        if cr_min is not None:
            kwargs["cr_min"] = cr_min
        if cr_max is not None:
            kwargs["cr_max"] = cr_max
        if creature_type:
            kwargs["type"] = creature_type
        r = await self._call("search_catalog", **kwargs)
        return (r or {}).get("monsters", [])

    async def search_items(
        self,
        name: str = "",
        rarity: str = "",
        item_type: str = "",
    ) -> list[dict]:
        kwargs: dict = {"category": "item"}
        if name:
            kwargs["name"] = name
        if rarity:
            kwargs["rarity"] = rarity.lower()
        if item_type:
            kwargs["item_type"] = item_type
        r = await self._call("search_catalog", **kwargs)
        return (r or {}).get("items", [])

    # ------------------------------------------------------------------
    # Module population
    # ------------------------------------------------------------------

    async def add_monster(
        self,
        module_id: str,
        monster_name: str,
        count: int = 1,
        notes: str = "",
    ) -> bool:
        r = await self._call(
            "add_monster_to_module",
            module_id=module_id,
            monster_name=monster_name,
            count=count,
            notes=notes,
        )
        return bool(r)

    async def add_item(self, module_id: str, item_name: str, notes: str = "") -> bool:
        r = await self._call("add_item_to_module", module_id=module_id, item_name=item_name, notes=notes)
        return bool(r)

    async def add_document(
        self,
        title: str,
        doc_type: str,
        content: str,
        module_id: Optional[str] = None,   # omit for campaign-level documents
    ) -> Optional[str]:
        """Create document. Returns document ID or None."""
        kwargs: dict = {"title": title, "document_type": doc_type, "content": content}
        if module_id:
            kwargs["module_id"] = module_id
        r = await self._call("create_document", **kwargs)
        doc = (r or {}).get("document", r or {})
        return doc.get("id") if isinstance(doc, dict) else None

    async def read_document(self, document_id: str) -> Optional[dict]:
        r = await self._call("read_document", document_id=document_id)
        return (r or {}).get("document", r)

    async def list_documents(self, module_id: Optional[str] = None) -> list:
        kwargs: dict = {}
        if module_id:
            kwargs["module_id"] = module_id
        r = await self._call("list_documents", **kwargs)
        return (r or {}).get("documents", [])

    async def delete_document(self, document_id: str) -> bool:
        r = await self._call("delete_document", document_id=document_id)
        return bool(r)

    async def upload_map(self, module_id: str, name: str, file_path: str) -> Optional[dict]:
        r = await self._call("create_map", module_id=module_id, name=name, file_path=file_path)
        return (r or {}).get("map")

    # ------------------------------------------------------------------
    # Homebrew
    # ------------------------------------------------------------------

    async def create_homebrew_item(
        self,
        name: str,
        item_type: str = "adventuring gear",
        rarity: str = "common",
        description: str = "",
    ) -> Optional[dict]:
        data = json.dumps({"entries": [description or name]})
        r = await self._call(
            "create_homebrew",
            content_type="item",
            name=name,
            data=data,
            item_type=item_type,
            rarity=rarity,
        )
        return (r or {}).get("homebrew")

    async def create_homebrew_monster(
        self,
        name: str,
        data_json: str,
        cr: str = "1",
        creature_type: str = "humanoid",
        size: str = "Medium",
        cloned_from: str = "",
        cloned_source: str = "",
    ) -> Optional[dict]:
        kwargs: dict = dict(
            content_type="monster",
            name=name,
            data=data_json,
            cr=cr,
            creature_type=creature_type,
            size=size,
        )
        if cloned_from:
            kwargs["cloned_from_name"] = cloned_from
            kwargs["cloned_from_source"] = cloned_source or "MM"
        r = await self._call("create_homebrew", **kwargs)
        return (r or {}).get("homebrew")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_mimir = MimirClient()


def get_mimir() -> MimirClient:
    """Return the global Mimir client (may not be connected yet)."""
    return _mimir

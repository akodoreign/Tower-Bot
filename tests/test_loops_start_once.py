"""A second on_ready (new gateway session) must not start the background loops again."""


async def test_process_messages_starts_loops_only_once():
    from src.aclient import DiscordClient

    client = object.__new__(DiscordClient)
    client._loops_started = True                 # the first on_ready already ran

    def must_not_start():
        raise AssertionError("background loops started a second time")

    client.discord_heartbeat_loop = must_not_start   # the first loop process_messages starts
    assert await client.process_messages() is None

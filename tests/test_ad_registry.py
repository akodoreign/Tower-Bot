"""Generated ads in MySQL, and the pooling bug that silently dropped child rows.

The nightly ad study appended each ad to a 34KB JSON list in global_state, and
every consumer loaded the whole blob to pick ONE ad:

    ad_feed         -> ads with a shop_name, then random.choice
    party_interview -> ad_type in ('shop','tourism'), then random.choice

That is WHERE ... ORDER BY RAND() LIMIT 1 written the long way, over exactly the
fields the JSON reflex check says belong in columns.
"""

import inspect

from src import ad_registry as ar


def test_pick_filters_in_sql_not_in_python():
    src = inspect.getsource(ar.pick_ad)
    assert "ORDER BY RAND() LIMIT 1" in src
    assert "ad_type IN" in src


def test_consumers_no_longer_read_the_blob():
    from src import ad_feed, party_interview

    for mod in (ad_feed, party_interview):
        src = inspect.getsource(mod)
        assert 'get_global_state("generated_ads")' not in src, (
            f"{mod.__name__} still loads the JSON blob"
        )


def test_writer_uses_the_table():
    from src import self_learning

    src = inspect.getsource(self_learning._study_ad_generation)
    assert "add_ad" in src
    assert 'set_global_state("generated_ads"' not in src


# ---------------------------------------------------------------------------
# The pooling bug
#
# "INSERT ...; SELECT LAST_INSERT_ID()" hands the SELECT a DIFFERENT pooled
# connection, where LAST_INSERT_ID() is 0 or someone else's. The parent row
# lands, the function returns no id, and the child rows are silently dropped --
# which looks exactly like success.
#
# Observed: the ad migration wrote 109 ads and 178 of ~316 tags, all 178 of them
# orphaned onto ad_id 0. The council migration wrote 110 rulings and ZERO votes,
# and it was reported as clean.
# ---------------------------------------------------------------------------

def _code_only(src: str) -> str:
    """Comments explaining why NOT to use LAST_INSERT_ID are not usages of it."""
    return " ".join(l for l in src.splitlines() if not l.strip().startswith("#"))


def test_ads_do_not_use_last_insert_id():
    src = _code_only(inspect.getsource(ar.add_ad))
    assert "LAST_INSERT_ID" not in src, "child rows will be orphaned across the pool"
    assert "db.insert(" in src, "use the helper that returns cursor.lastrowid"


def test_council_does_not_use_last_insert_id():
    from src import council_registry as cr

    src = _code_only(inspect.getsource(cr.record_ruling))
    assert "LAST_INSERT_ID" not in src
    assert "db.insert(" in src


def test_no_id_means_no_orphaned_children():
    """If the id cannot be obtained, refuse rather than write parentless rows."""
    for fn in (ar.add_ad,):
        src = inspect.getsource(fn)
        assert "if not ad_id" in src

    from src import council_registry as cr
    assert "if not ruling_id" in inspect.getsource(cr.record_ruling)

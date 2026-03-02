"""Inventory guard for repository executable-artifact coverage policy."""

from __future__ import annotations

from tests.utils.executable_artifact_manifest import (
    EXECUTABLE_NON_SQL_SET,
    SQL_EQUIVALENCE_PAIRS,
    SQL_EXCLUDED_SET,
    SQL_EXECUTE_SET,
    sql_equivalence_duplicate_set,
    tracked_executable_artifacts,
)


def test_every_tracked_executable_artifact_is_classified_exactly_once() -> None:
    tracked = tracked_executable_artifacts()
    duplicates = sql_equivalence_duplicate_set()
    classified = SQL_EXECUTE_SET | SQL_EXCLUDED_SET | EXECUTABLE_NON_SQL_SET | duplicates

    assert tracked == classified, (
        "Tracked executable artifacts and coverage manifest classification diverged. "
        f"missing_classification={sorted(tracked - classified)}, "
        f"extra_classification={sorted(classified - tracked)}"
    )


def test_sql_classification_buckets_are_disjoint() -> None:
    duplicates = sql_equivalence_duplicate_set()

    assert SQL_EXECUTE_SET.isdisjoint(SQL_EXCLUDED_SET), "SQL execute/excluded sets must be disjoint."
    assert SQL_EXECUTE_SET.isdisjoint(duplicates), "SQL execute/equivalence duplicate sets must be disjoint."
    assert SQL_EXCLUDED_SET.isdisjoint(duplicates), "SQL excluded/equivalence duplicate sets must be disjoint."


def test_sql_equivalence_pairs_target_existing_paths() -> None:
    tracked = tracked_executable_artifacts()
    for duplicate, canonical in SQL_EQUIVALENCE_PAIRS:
        assert duplicate in tracked, f"Equivalence duplicate path is not tracked: {duplicate}"
        assert canonical in tracked, f"Equivalence canonical path is not tracked: {canonical}"

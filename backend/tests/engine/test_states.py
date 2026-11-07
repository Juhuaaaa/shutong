import unittest

from shutong.engine.states import (
    InvalidTransition,
    ItemStatus,
    TRANSITIONS,
    check_transition,
)


class StateMachineTests(unittest.TestCase):
    def test_every_status_has_transition_entry(self):
        self.assertEqual(set(TRANSITIONS), set(ItemStatus))

    def test_duplicate_can_only_be_parsed_again(self):
        self.assertEqual(TRANSITIONS[ItemStatus.DUPLICATE], frozenset({ItemStatus.PARSED}))

    def test_rejects_skipping_to_published(self):
        with self.assertRaises(InvalidTransition):
            check_transition(ItemStatus.READY, ItemStatus.PUBLISHED)

    def test_republish_path(self):
        check_transition(ItemStatus.PUBLISHED, ItemStatus.READY)

    def test_build_can_return_to_ready_after_cancel(self):
        check_transition(ItemStatus.BUILDING, ItemStatus.READY)

    def test_matched_can_become_duplicate(self):
        # The library's existing volumes are only known while planning.
        check_transition(ItemStatus.MATCHED, ItemStatus.DUPLICATE)

    def test_matched_can_be_published_by_claim(self):
        check_transition(ItemStatus.MATCHED, ItemStatus.PUBLISHED)


if __name__ == "__main__":
    unittest.main()

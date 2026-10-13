from unittest import TestCase

from localpilot.models.model_manager import ResourceSnapshot, check_compatibility

GIB = 1024**3


class CompatibilityTests(TestCase):
    def test_lightweight_profile_accepts_sufficient_memory(self) -> None:
        result = check_compatibility("lightweight", ResourceSnapshot(8 * GIB, 4 * GIB, "test"))
        self.assertTrue(result.compatible)

    def test_12b_profile_refuses_eight_gib_machine(self) -> None:
        result = check_compatibility("12b", ResourceSnapshot(8 * GIB, 7 * GIB, "test"))
        self.assertFalse(result.compatible)
        self.assertIn("refused", result.reason)

    def test_training_has_separate_high_memory_guard(self) -> None:
        result = check_compatibility("training", ResourceSnapshot(64 * GIB, 40 * GIB, "test"))
        self.assertTrue(result.compatible)

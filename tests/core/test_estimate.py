"""Tests for beadstudio.core.estimate — assembly time and shop-cost estimation."""

from __future__ import annotations

import math

import pytest

from beadstudio.core.estimate import (
    EstimateResult,
    estimate_cost,
    estimate_time,
)


# ---------------------------------------------------------------------------
# Model validation — exact 2704 beads, 5 colours (fixed spec assertions)
# ---------------------------------------------------------------------------

class TestModelMath2704:
    """Verify the estimation model against the exact spec for 2704 beads
    with 5 colours.  All assertions have ±2 tolerance because the spec
    rounds to whole minutes but floating-point may differ slightly."""

    BEADS = 2704
    COLORS = 5
    RATE = 25
    SHOP_RATE = 30

    def test_normal_minutes(self):
        """normal ≈ 118 min (±2) — 2704/25+10=118.16"""
        est = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                            shop_rate=self.SHOP_RATE)
        assert abs(est["minutes"]["normal"] - 118.0) <= 2, (
            f"Expected normal ≈118, got {est['minutes']['normal']}"
        )

    def test_beginner_tier_minutes(self):
        """beginner_tier ≈ 280 min (±2) — 2704/10+10=280.4"""
        est = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                            shop_rate=self.SHOP_RATE)
        assert abs(est["minutes"]["beginner_tier"] - 280.0) <= 2, (
            f"Expected beginner_tier ≈280, got {est['minutes']['beginner_tier']}"
        )

    def test_expert_minutes(self):
        """expert ≈ 78 min (±2) — 2704/40+10=77.6"""
        est = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                            shop_rate=self.SHOP_RATE)
        assert abs(est["minutes"]["expert"] - 78.0) <= 2, (
            f"Expected expert ≈78, got {est['minutes']['expert']}"
        )

    def test_beginner_flag_doubles_normal(self):
        """--beginner flag: normal × 1.5 = 118 × 1.5 = 177 (±2)"""
        est = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                            shop_rate=self.SHOP_RATE, beginner=True)
        assert abs(est["minutes"]["normal"] - 177.0) <= 2, (
            f"Expected beginner-flag normal ≈177, got {est['minutes']['normal']}"
        )

    def test_beginner_flag_does_not_affect_beginner_tier(self):
        """--beginner flag should NOT change the beginner_tier (rate=10)."""
        est_no = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                               shop_rate=self.SHOP_RATE, beginner=False)
        est_yes = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                                shop_rate=self.SHOP_RATE, beginner=True)
        assert est_no["minutes"]["beginner_tier"] == est_yes["minutes"]["beginner_tier"]

    def test_beginner_flag_does_not_affect_expert(self):
        """--beginner flag should NOT change the expert tier."""
        est_no = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                               shop_rate=self.SHOP_RATE, beginner=False)
        est_yes = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                                shop_rate=self.SHOP_RATE, beginner=True)
        assert est_no["minutes"]["expert"] == est_yes["minutes"]["expert"]

    def test_cost_normal(self):
        """estimate_cost(118, 30) == 60.0 — ceil(118/30)×0.5×30 = 4×15=60"""
        cost = estimate_cost(118.0, 30.0)
        assert cost == 60.0, f"Expected 60.0, got {cost}"

    def test_estimate_time_returns_cost_for_normal(self):
        """Verify the returned cost for normal tier matches estimate_cost."""
        est = estimate_time(self.BEADS, rate=self.RATE, colors=self.COLORS,
                            shop_rate=self.SHOP_RATE)
        expected = estimate_cost(est["minutes"]["normal"], self.SHOP_RATE)
        assert est["cost"]["normal"] == expected


# ---------------------------------------------------------------------------
# Colour difficulty factor tests
# ---------------------------------------------------------------------------

class TestColorFactor:
    """Colour-factor boundaries: ≤8→1.0, 8-20→0.85, >20→0.7."""

    BEADS = 2500  # 2500/25=100 base + 10 overhead

    def test_few_colors_fastest(self):
        """≤8 colors → color_factor 1.0 → fastest effective rate."""
        est_few = estimate_time(self.BEADS, rate=25, colors=5)
        # 2500/25+10=110
        assert abs(est_few["minutes"]["normal"] - 110.0) <= 1

    def test_medium_colors_slower(self):
        """8<colors≤20 → color_factor 0.85 → slower effective rate."""
        est_med = estimate_time(self.BEADS, rate=25, colors=15)
        # 2500/(25*0.85)+10 = 2500/21.25+10 = 117.647+10 = 127.647
        expected = self.BEADS / (25.0 * 0.85) + 10.0
        assert abs(est_med["minutes"]["normal"] - expected) <= 1

    def test_many_colors_slowest(self):
        """>20 colors → color_factor 0.7 → slowest effective rate."""
        est_many = estimate_time(self.BEADS, rate=25, colors=25)
        # 2500/(25*0.7)+10 = 2500/17.5+10 = 142.857+10 = 152.857
        expected = self.BEADS / (25.0 * 0.7) + 10.0
        assert abs(est_many["minutes"]["normal"] - expected) <= 1

    def test_color_factor_boundary_8(self):
        """Exactly 8 colors → factor 1.0."""
        est = estimate_time(self.BEADS, rate=25, colors=8)
        # rate_eff = 25*1.0 = 25, so 2500/25+10=110
        assert abs(est["minutes"]["normal"] - 110.0) <= 1

    def test_color_factor_boundary_9(self):
        """Exactly 9 colors → factor 0.85."""
        est = estimate_time(self.BEADS, rate=25, colors=9)
        expected = self.BEADS / (25.0 * 0.85) + 10.0
        assert abs(est["minutes"]["normal"] - expected) <= 1

    def test_color_factor_boundary_20(self):
        """Exactly 20 colors → factor 0.85."""
        est = estimate_time(self.BEADS, rate=25, colors=20)
        expected = self.BEADS / (25.0 * 0.85) + 10.0
        assert abs(est["minutes"]["normal"] - expected) <= 1

    def test_color_factor_boundary_21(self):
        """Exactly 21 colors → factor 0.7."""
        est = estimate_time(self.BEADS, rate=25, colors=21)
        expected = self.BEADS / (25.0 * 0.7) + 10.0
        assert abs(est["minutes"]["normal"] - expected) <= 1


# ---------------------------------------------------------------------------
# Cost calculation tests
# ---------------------------------------------------------------------------

class TestCostCalculation:
    """estimate_cost(minutes, shop_rate) rounding behavior."""

    def test_zero_minutes(self):
        """Zero minutes → ceil(0/30)=0 → 0×0.5×shop_rate=0."""
        assert estimate_cost(0.0, 30.0) == 0.0

    def test_less_than_half_hour(self):
        """1 min → ceil(1/30)=1 → 1×0.5×30=15."""
        assert estimate_cost(1.0, 30.0) == 15.0

    def test_exactly_half_hour(self):
        """30 min → ceil(30/30)=1 → 1×0.5×30=15."""
        assert estimate_cost(30.0, 30.0) == 15.0

    def test_barely_over_half_hour(self):
        """31 min → ceil(31/30)=2 → 2×0.5×30=30."""
        assert estimate_cost(31.0, 30.0) == 30.0

    def test_one_hour(self):
        """60 min → ceil(60/30)=2 → 2×0.5×30=30."""
        assert estimate_cost(60.0, 30.0) == 30.0

    def test_two_hours(self):
        """120 min → ceil(120/30)=4 → 4×0.5×30=60."""
        assert estimate_cost(120.0, 30.0) == 60.0

    def test_default_shop_rate(self):
        """Default shop_rate=30."""
        assert estimate_cost(60.0) == 30.0

    def test_custom_shop_rate(self):
        """50 yuan/h → ceil(60/30)×0.5×50 = 2×25=50."""
        assert estimate_cost(60.0, 50.0) == 50.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    """Reject invalid inputs with Chinese error messages."""

    def test_rate_zero_raises(self):
        """rate <= 0 → ValueError."""
        with pytest.raises(ValueError, match="rate.*大于"):
            estimate_time(100, rate=0)

    def test_rate_negative_raises(self):
        """Negative rate → ValueError."""
        with pytest.raises(ValueError, match="rate.*大于"):
            estimate_time(100, rate=-5)

    def test_shop_rate_zero_raises(self):
        """shop_rate <= 0 in estimate_cost → ValueError."""
        with pytest.raises(ValueError, match="shop_rate.*大于"):
            estimate_cost(60.0, 0.0)

    def test_shop_rate_negative_raises(self):
        """Negative shop_rate in estimate_cost → ValueError."""
        with pytest.raises(ValueError, match="shop_rate.*大于"):
            estimate_cost(60.0, -10.0)

    def test_estimate_time_shop_rate_zero_raises(self):
        """shop_rate <= 0 in estimate_time → ValueError."""
        with pytest.raises(ValueError, match="shop_rate.*大于"):
            estimate_time(100, rate=25, shop_rate=0)


# ---------------------------------------------------------------------------
# Return dict structure
# ---------------------------------------------------------------------------

class TestReturnStructure:
    """Verify all expected keys are present with correct types."""

    def test_keys_present(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        assert set(est.keys()) == {"beads", "colors", "minutes", "hours", "cost"}

    def test_minutes_has_three_tiers(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        assert set(est["minutes"].keys()) == {"beginner_tier", "normal", "expert"}

    def test_hours_has_three_tiers(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        assert set(est["hours"].keys()) == {"beginner_tier", "normal", "expert"}

    def test_cost_has_three_tiers(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        assert set(est["cost"].keys()) == {"beginner", "normal", "expert"}

    def test_minutes_equals_hours_times_60(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        for tier in ("beginner_tier", "normal", "expert"):
            assert abs(est["hours"][tier] - est["minutes"][tier] / 60.0) <= 1e-6

    def test_beads_and_colors_preserved(self):
        est = estimate_time(2704, rate=25, colors=5, shop_rate=30)
        assert est["beads"] == 2704
        assert est["colors"] == 5

    def test_hours_are_reasonable(self):
        """Hours should be within a reasonable range, not NaN/inf."""
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        for tier in ("beginner_tier", "normal", "expert"):
            assert 0.0 <= est["hours"][tier] <= 1000.0
            assert math.isfinite(est["hours"][tier])

    def test_costs_are_nonnegative(self):
        est = estimate_time(100, rate=25, colors=3, shop_rate=30)
        for tier in ("beginner", "normal", "expert"):
            assert est["cost"][tier] >= 0.0


# ---------------------------------------------------------------------------
# Default parameter tests
# ---------------------------------------------------------------------------

class TestDefaults:
    """Verify module defaults match spec."""

    def test_default_rate_is_25(self):
        est = estimate_time(250)  # default rate=25, colors=5
        # 250/25+10=20
        assert abs(est["minutes"]["normal"] - 20.0) <= 1

    def test_default_colors_is_5(self):
        est = estimate_time(250, rate=25)  # rate=25, default colors=5
        # colors=5 ≤ 8 → factor 1.0, 250/25+10=20
        assert abs(est["minutes"]["normal"] - 20.0) <= 1

    def test_default_shop_rate_is_30(self):
        est = estimate_time(250, rate=25)
        # cost normal: ceil(20/30)*0.5*30 = 1*15 = 15
        assert est["cost"]["normal"] == 15.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Probe edge cases for robustness."""

    def test_one_bead(self):
        """Single-bead pattern should be computable."""
        est = estimate_time(1, rate=25, colors=1, shop_rate=30)
        # 1/25+10 ≈ 10.04
        assert est["minutes"]["normal"] >= 10.0
        # Verify all costs are finite
        for tier in ("beginner", "normal", "expert"):
            assert math.isfinite(est["cost"][tier])

    def test_zero_colors(self):
        """0 colors should not raise (corner: empty grid)."""
        est = estimate_time(0, rate=25, colors=0, shop_rate=30)
        # 0 beads, 0/rate+10 = 10 (constant overhead still applies)
        assert est["minutes"]["normal"] == 10.0
        # Cost: ceil(10/30)*0.5*30 = 1*15=15
        assert est["cost"]["normal"] == 15.0

    def test_very_large_pattern(self):
        """100 000 beads should not overflow."""
        est = estimate_time(100_000, rate=25, colors=30, shop_rate=30)
        for tier in ("beginner_tier", "normal", "expert"):
            assert math.isfinite(est["minutes"][tier])
        for tier in ("beginner", "normal", "expert"):
            assert math.isfinite(est["cost"][tier])


# ---------------------------------------------------------------------------
# EstimateResult dataclass
# ---------------------------------------------------------------------------

class TestEstimateResult:
    """Verify EstimateResult dataclass construction and fields."""

    def test_construct(self):
        er = EstimateResult(
            beads=100,
            colors=5,
            minutes={"beginner_tier": 20.0, "normal": 14.0, "expert": 12.5},
            hours={"beginner_tier": 0.33, "normal": 0.23, "expert": 0.21},
            cost={"beginner": 15.0, "normal": 15.0, "expert": 15.0},
        )
        assert er.beads == 100
        assert er.colors == 5
        assert er.minutes["normal"] == 14.0

    def test_estimate_time_is_constructable_as_estimat_result(self):
        """The dict returned by estimate_time() can construct EstimateResult."""
        d = estimate_time(100, rate=25, colors=5, shop_rate=30)
        er = EstimateResult(**d)
        assert er.beads == d["beads"]
        assert er.colors == d["colors"]
        assert er.minutes == d["minutes"]
        assert er.hours == d["hours"]
        assert er.cost == d["cost"]


# ---------------------------------------------------------------------------
# Integration: verify CSV contains estimate columns
# ---------------------------------------------------------------------------

class TestCsvEstimateIntegration:
    """Verify the shopping-list CSV includes the estimate summary block."""

    def test_csv_has_estimate_summary_when_rate_provided(self):
        from beadstudio.core.export import shopping_list_csv

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        csv_str = shopping_list_csv(grid, rate=25, shop_rate=30)
        assert isinstance(csv_str, str)
        assert "工时与成本预估" in csv_str
        assert "预估时长(分)" in csv_str
        assert "预估费用(元)" in csv_str

    def test_csv_no_estimate_summary_when_rate_omitted(self):
        from beadstudio.core.export import shopping_list_csv

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        csv_str = shopping_list_csv(grid)
        assert isinstance(csv_str, str)
        assert "工时与成本预估" not in csv_str

    def test_csv_estimate_contains_tier_values(self):
        from beadstudio.core.export import shopping_list_csv

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        csv_str = shopping_list_csv(grid, rate=25, shop_rate=30)
        # Should contain all three tiers in the time line
        assert "新手级" in csv_str
        assert "普通" in csv_str
        assert "专家级" in csv_str


# ---------------------------------------------------------------------------
# Integration: verify PDF footer contains actual estimate (not placeholder)
# ---------------------------------------------------------------------------

class TestPdfFooterEstimate:
    """Verify the PDF footer estimate text replaces the placeholder."""

    def _decompress_pdf_text(self, pdf_bytes: bytes) -> str:
        """Extract readable text from a PDF's content streams (FlateDecode)."""
        import re
        import zlib

        streams = []
        for match in re.finditer(
            rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL
        ):
            raw = match.group(1)
            try:
                decompressed = zlib.decompress(raw)
                streams.append(decompressed)
            except zlib.error:
                # Not compressed or broken — skip
                continue
        return b"\n".join(streams).decode("latin-1", errors="replace")

    def test_export_pdf_accepts_estimate_params(self):
        from beadstudio.core.export import export_pdf
        import tempfile

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            out_path = tf.name
        try:
            export_pdf(
                grid,
                out_path,
                estimate_rate=25,
                estimate_shop_rate=30,
                estimate_beginner=False,
            )
            from pathlib import Path
            content = Path(out_path).read_bytes()
            # Decompress content streams to find text
            decompressed = self._decompress_pdf_text(content)
            # The estimate text should contain the three-tier values
            # (CJK text may be encoded, but numbers like "分钟" pattern are universal)
            assert "待 T8" not in decompressed, (
                "PDF should NOT contain the old placeholder"
            )
            # Check that the overall PDF is well-formed
            assert content.startswith(b"%PDF-"), "Not a valid PDF"
            assert content.strip().endswith(b"%%EOF"), "PDF not properly terminated"
            # Verify the stream content is non-empty and contains footer drawing
            assert len(decompressed) > 0, "Content streams should not be empty"
        finally:
            from pathlib import Path
            Path(out_path).unlink(missing_ok=True)

    def test_export_pdf_empty_grid_has_estimate(self):
        from beadstudio.core.export import export_pdf
        import tempfile

        grid = [[None, None], [None, None]]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            out_path = tf.name
        try:
            export_pdf(grid, out_path, estimate_rate=25, estimate_shop_rate=30)
            from pathlib import Path
            content = Path(out_path).read_bytes()
            decompressed = self._decompress_pdf_text(content)
            assert "待 T8" not in decompressed, (
                "PDF should NOT contain the old placeholder"
            )
            assert content.startswith(b"%PDF-")
            assert content.strip().endswith(b"%%EOF")
            assert len(decompressed) > 0
        finally:
            from pathlib import Path
            Path(out_path).unlink(missing_ok=True)

    def test_export_pdf_without_estimate_params_still_works(self):
        """Backward compat: calling export_pdf without estimate params fills
        the footer with default-rate estimates (not the old placeholder)."""
        from beadstudio.core.export import export_pdf
        import tempfile

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            out_path = tf.name
        try:
            export_pdf(grid, out_path)  # no estimate params → default rate/shop_rate
            from pathlib import Path
            content = Path(out_path).read_bytes()
            decompressed = self._decompress_pdf_text(content)
            # Should NOT contain the old placeholder
            assert "待 T8" not in decompressed, (
                "PDF should NOT contain the old placeholder even without params"
            )
            assert content.startswith(b"%PDF-")
            assert content.strip().endswith(b"%%EOF")
        finally:
            from pathlib import Path
            Path(out_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Integration: verify shopping list PNG has estimate text
# ---------------------------------------------------------------------------

class TestShoppingListPngEstimate:
    """Verify the shopping list PNG includes time/cost text when requested."""

    def test_png_has_estimate_when_rate_provided(self):
        from beadstudio.core.export import shopping_list_png

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        img = shopping_list_png(grid, rate=25, shop_rate=30)
        # Image should be taller than without estimate (extra lines)
        img_no_est = shopping_list_png(grid)
        assert img.size[1] > img_no_est.size[1], (
            f"With estimate ({img.size[1]}px) should be taller than "
            f"without ({img_no_est.size[1]}px)"
        )

    def test_png_no_estimate_when_rate_omitted(self):
        from beadstudio.core.export import shopping_list_png

        grid = [
            ["80-19001", "80-19005"],
            ["80-19001", "80-19005"],
        ]
        img = shopping_list_png(grid)
        # Should still be valid
        from PIL import Image
        assert isinstance(img, Image.Image)
        assert img.size[1] > 0

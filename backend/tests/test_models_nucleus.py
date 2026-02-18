"""
Tests for app.models.nucleus — ORM model definitions.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from app.models.nucleus import AnalysisBox, Nucleus, Slide


class TestSlideModel:
    def test_tablename(self):
        assert Slide.__tablename__ == "slides"

    def test_columns_exist(self):
        cols = {c.name for c in Slide.__table__.columns}
        expected = {
            "id", "filename", "filepath", "mpp",
            "width_px", "height_px", "metadata",
            "created_at", "updated_at",
        }
        assert expected.issubset(cols)

    def test_has_analysis_boxes_relationship(self):
        assert hasattr(Slide, "analysis_boxes")


class TestAnalysisBoxModel:
    def test_tablename(self):
        assert AnalysisBox.__tablename__ == "analysis_boxes"

    def test_columns_exist(self):
        cols = {c.name for c in AnalysisBox.__table__.columns}
        expected = {
            "id", "slide_id", "label",
            "x_min", "y_min", "x_max", "y_max",
            "geom", "total_nuclei", "area_mm2",
            "density_per_mm2", "neoplastic_ratio",
            "cell_type_counts", "created_at",
        }
        assert expected.issubset(cols)

    def test_has_slide_relationship(self):
        assert hasattr(AnalysisBox, "slide")

    def test_has_nuclei_relationship(self):
        assert hasattr(AnalysisBox, "nuclei")


class TestNucleusModel:
    def test_tablename(self):
        assert Nucleus.__tablename__ == "nuclei"

    def test_columns_exist(self):
        cols = {c.name for c in Nucleus.__table__.columns}
        expected = {
            "id", "slide_id", "analysis_box_id",
            "geom", "contour",
            "cell_type", "cell_type_name",
            "probability", "area_um2", "perimeter_um",
            "created_at",
        }
        assert expected.issubset(cols)

    def test_has_slide_relationship(self):
        assert hasattr(Nucleus, "slide")

    def test_has_analysis_box_relationship(self):
        assert hasattr(Nucleus, "analysis_box")

    def test_probability_check_constraint(self):
        """Verify the check constraint for probability is defined."""
        constraints = [c.name for c in Nucleus.__table__.constraints if hasattr(c, 'name') and c.name]
        assert "ck_nuclei_probability_range" in constraints

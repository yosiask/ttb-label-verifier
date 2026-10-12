"""All decision thresholds in one place.

These are starting values from the design brief, not proof of accuracy. They are
tuned against the fixtures in Milestone 4 and the final values are recorded in the
README with the reason for each.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Text fields: (pass at or above, needs review at or above, otherwise fail)
    brand_pass: float = 95
    brand_review: float = 85
    class_type_pass: float = 92
    class_type_review: float = 80
    producer_pass: float = 90
    producer_review: float = 75
    country_pass: float = 90
    country_review: float = 75

    # A full-text hit only counts as the field when the match covers this much of its line.
    line_coverage_min: float = 0.80

    abv_tolerance: float = 0.05  # percentage points
    proof_tolerance: float = 0.1  # proof degrees
    net_contents_tolerance: float = 0.005  # 0.5 %

    # Image readability, on a 0..1 scale (mean OCR word confidence / 100).
    unreadable_below: float = 0.55
    low_confidence_below: float = 0.70

    # Government warning: OCR noise vs real violation.
    warning_noise_max_edits: int = 3
    warning_noise_word_conf: float = 80  # 0..100


THRESHOLDS = Thresholds()

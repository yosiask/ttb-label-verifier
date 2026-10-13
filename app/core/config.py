"""All decision thresholds in one place.

These are starting values from the design brief, not proof of accuracy. They are
tuned against the fixtures in Milestone 4 and the final values are recorded in the
README with the reason for each.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Text fields. Pass needs every expected word on the label exactly (ignoring case,
    # punctuation and spacing); fuzzy similarity never passes on its own. Similarity at or
    # above *_review is Needs review (near miss, shown with the differing words); below it
    # is Fail on a readable label. *_pass only changes the wording ("Nearly matches").
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
    # Offline OCR: below this mean word confidence over the warning, the small print was not read
    # reliably, so wording differences and a heading not read at all are Needs review, not Fail.
    # Measured mean confidence: clean fixtures ~95.7; hard photos (tiny, curved, glare) 69-85;
    # photo violations with altered or paraphrased words 89-91.
    warning_ocr_trust_conf: float = 86

    # Bold cross-check (heading stroke / body stroke from pixels). Fixtures: bold heading over a
    # regular body 1.8-2.0; same weight 0.95-1.03; blur and low resolution pull it toward 1.
    bold_heavier_ratio: float = 1.4  # at or above: heading clearly heavier than body
    bold_same_ratio: float = 1.15  # at or below: heading and body look the same weight


THRESHOLDS = Thresholds()

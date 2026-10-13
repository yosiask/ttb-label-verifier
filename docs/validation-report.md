# Validation report

**Measured** on https://ttb-label-verifier.salmonsky-e6ff55c6.eastus2.azurecontainerapps.io (2026-10-13 04:06 UTC) by `scripts/run_accuracy.py`: every fixture through the real HTTP API, 2 repetition(s) per engine. Round trips include the internet path from the test machine (a VPS outside Azure) to the app.

Fixtures are synthetic: `clean` are flat rendered labels; `photos` are simulated photographs (curvature, angle, glare, blur, small text, unusual fonts, front/back labels). They are not real photos of real products. Ground truth is hand-written in the generators.

| Engine | Set | Labels | As expected | False pass | False fail | Detection (Fail) | Flagged (not Pass) | Needs review | p50 / p95 round trip | Server p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| azure | clean | 48 | 48/48 (100%) | 0/28 (0%) | 0/20 (0%) | 20/24 (83%) | 24/24 (100%) | 8/44 (18%) | 3.8 s / 4.7 s | 3.5 s / 4.5 s |
| azure | photos | 62 | 58/62 (94%) | 0/36 (0%) | 0/26 (0%) | 24/32 (75%) | 32/32 (100%) | 34/58 (59%) | 4.6 s / 5.4 s | 4.2 s / 5.0 s |
| local | clean | 48 | 48/48 (100%) | 0/28 (0%) | 0/20 (0%) | 18/24 (75%) | 24/24 (100%) | 26/44 (59%) | 0.7 s / 1.0 s | 0.5 s / 0.7 s |
| local | photos | 62 | 50/62 (81%) | 0/36 (0%) | 12/26 (46%) | 26/32 (81%) | 32/32 (100%) | 20/58 (34%) | 1.3 s / 2.2 s | 1.0 s / 1.8 s |

False pass counts violations *and* labels whose right answer is Needs review. Needs review is over labels whose right answer is Pass or Fail.

- azure / clean: tokens: 88,214 in / 11,523 out over 48 labels = $0.059 ($0.0012 per label at list price).
- azure / photos: tokens: 112,414 in / 15,956 out over 62 labels = $0.077 ($0.0013 per label at list price).

## Per label

| Engine | Set | Label | Truth | Verdicts | Accepted | Notes |
|---|---|---|---|---|---|---|
| azure | clean | abv_mismatch | violation | fail, fail | fail |  |
| azure | clean | abv_mismatch_tilted | violation | fail, fail | fail/needs_review |  |
| azure | clean | blank_or_unreadable | review | needs_review, needs_review | needs_review |  |
| azure | clean | blurry | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | clean | brand_case_diff | compliant | pass, pass | pass |  |
| azure | clean | brand_one_letter_off | review | needs_review, needs_review | needs_review |  |
| azure | clean | brand_only_in_address | violation | needs_review, needs_review | needs_review/fail |  |
| azure | clean | brand_wrong | violation | fail, fail | fail |  |
| azure | clean | clean_spirits | compliant | pass, pass | pass |  |
| azure | clean | dim | compliant | pass, pass | pass/needs_review |  |
| azure | clean | exif_rotated | compliant | pass, pass | pass |  |
| azure | clean | glare | compliant | pass, pass | pass/needs_review |  |
| azure | clean | import_country_ok | compliant | pass, pass | pass |  |
| azure | clean | import_no_country | violation | fail, fail | fail |  |
| azure | clean | low_res | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | clean | net_contents_units | compliant | pass, pass | pass |  |
| azure | clean | proof_inconsistent | violation | fail, fail | fail |  |
| azure | clean | tilted_10deg | compliant | pass, pass | pass/needs_review |  |
| azure | clean | warning_altered_word | violation | fail, fail | fail |  |
| azure | clean | warning_body_bold | violation | fail, fail | fail |  |
| azure | clean | warning_heading_not_bold | violation | needs_review, needs_review | fail/needs_review |  |
| azure | clean | warning_missing | violation | fail, fail | fail |  |
| azure | clean | warning_missing_colon | violation | fail, fail | fail |  |
| azure | clean | warning_title_case | violation | fail, fail | fail |  |
| azure | photos | abv_mismatch_photo | violation | fail, fail | fail |  |
| azure | photos | beer_abv_mismatch | violation | fail, fail | fail |  |
| azure | photos | beer_blackletter | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_angled | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_curved | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_front_back | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_glare_side | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_glare_warning | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_small_photo | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_soft_focus | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | bourbon_tiny_warning | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | brand_case_styled | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | brand_different | violation | fail, fail | fail |  |
| azure | photos | brand_one_letter_photo | review | needs_review, needs_review | needs_review |  |
| azure | photos | front_only | review | needs_review, needs_review | needs_review |  |
| azure | photos | import_no_country_photo | violation | needs_review, needs_review | fail | country_of_origin: ['needs_review', 'fail'] |
| azure | photos | net_contents_mismatch | violation | fail, fail | fail |  |
| azure | photos | proof_inconsistent_photo | violation | fail, fail | fail |  |
| azure | photos | scotch_import | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | vodka_dark_label | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | photos | vodka_warning_lowercase | violation | fail, fail | fail |  |
| azure | photos | warning_all_bold | violation | needs_review, needs_review | fail/needs_review |  |
| azure | photos | warning_altered_under_glare | violation | fail, fail | fail/needs_review |  |
| azure | photos | warning_altered_word | violation | fail, fail | fail |  |
| azure | photos | warning_heading_regular | violation | needs_review, needs_review | fail/needs_review |  |
| azure | photos | warning_missing_all_sides | violation | needs_review, needs_review | fail | government_warning: ['needs_review', 'fail'] |
| azure | photos | warning_missing_clause | violation | fail, fail | fail |  |
| azure | photos | warning_no_colon_back | violation | fail, fail | fail |  |
| azure | photos | warning_paraphrased | violation | fail, fail | fail |  |
| azure | photos | warning_title_case_curved | violation | fail, fail | fail |  |
| azure | photos | wine_script_front_back | compliant | needs_review, needs_review | pass/needs_review |  |
| local | clean | abv_mismatch | violation | fail, fail | fail |  |
| local | clean | abv_mismatch_tilted | violation | fail, fail | fail/needs_review |  |
| local | clean | blank_or_unreadable | review | needs_review, needs_review | needs_review |  |
| local | clean | blurry | compliant | needs_review, needs_review | needs_review |  |
| local | clean | brand_case_diff | compliant | needs_review, needs_review | needs_review |  |
| local | clean | brand_one_letter_off | review | needs_review, needs_review | needs_review |  |
| local | clean | brand_only_in_address | violation | needs_review, needs_review | needs_review |  |
| local | clean | brand_wrong | violation | fail, fail | fail |  |
| local | clean | clean_spirits | compliant | needs_review, needs_review | needs_review |  |
| local | clean | dim | compliant | needs_review, needs_review | needs_review |  |
| local | clean | exif_rotated | compliant | needs_review, needs_review | needs_review |  |
| local | clean | glare | compliant | needs_review, needs_review | needs_review |  |
| local | clean | import_country_ok | compliant | needs_review, needs_review | needs_review |  |
| local | clean | import_no_country | violation | fail, fail | fail |  |
| local | clean | low_res | compliant | needs_review, needs_review | needs_review |  |
| local | clean | net_contents_units | compliant | needs_review, needs_review | needs_review |  |
| local | clean | proof_inconsistent | violation | fail, fail | fail |  |
| local | clean | tilted_10deg | compliant | needs_review, needs_review | needs_review |  |
| local | clean | warning_altered_word | violation | fail, fail | fail |  |
| local | clean | warning_body_bold | violation | needs_review, needs_review | needs_review |  |
| local | clean | warning_heading_not_bold | violation | needs_review, needs_review | needs_review |  |
| local | clean | warning_missing | violation | fail, fail | fail |  |
| local | clean | warning_missing_colon | violation | fail, fail | fail |  |
| local | clean | warning_title_case | violation | fail, fail | fail |  |
| local | photos | abv_mismatch_photo | violation | fail, fail | fail/needs_review |  |
| local | photos | beer_abv_mismatch | violation | fail, fail | fail/needs_review |  |
| local | photos | beer_blackletter | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_angled | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_curved | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_front_back | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_glare_side | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_glare_warning | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_small_photo | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_soft_focus | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_tiny_warning | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | brand_case_styled | compliant | needs_review, needs_review | needs_review |  |
| local | photos | brand_different | violation | needs_review, needs_review | fail/needs_review |  |
| local | photos | brand_one_letter_photo | review | needs_review, needs_review | needs_review |  |
| local | photos | front_only | review | needs_review, needs_review | needs_review |  |
| local | photos | import_no_country_photo | violation | fail, fail | fail/needs_review |  |
| local | photos | net_contents_mismatch | violation | fail, fail | fail/needs_review |  |
| local | photos | proof_inconsistent_photo | violation | fail, fail | fail/needs_review |  |
| local | photos | scotch_import | compliant | needs_review, needs_review | needs_review |  |
| local | photos | vodka_dark_label | compliant | needs_review, needs_review | needs_review |  |
| local | photos | vodka_warning_lowercase | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_all_bold | violation | needs_review, needs_review | fail/needs_review |  |
| local | photos | warning_altered_under_glare | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_altered_word | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_heading_regular | violation | needs_review, needs_review | fail/needs_review |  |
| local | photos | warning_missing_all_sides | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_missing_clause | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_no_colon_back | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_paraphrased | violation | fail, fail | fail/needs_review |  |
| local | photos | warning_title_case_curved | violation | fail, fail | fail/needs_review |  |
| local | photos | wine_script_front_back | compliant | needs_review, needs_review | needs_review |  |

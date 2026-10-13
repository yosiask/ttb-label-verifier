# Validation report

**Measured** on https://ttb-label-verifier.salmonsky-e6ff55c6.eastus2.azurecontainerapps.io (2026-10-13 12:22 UTC) by `scripts/run_accuracy.py`: every fixture through the real HTTP API, 2 repetition(s) per engine. Round trips include the internet path from the test machine (a VPS outside Azure) to the app.

Sets: `clean` are synthetic flat rendered labels; `photos` are simulated photographs (curvature, angle, glare, blur, small text, unusual fonts, front/back labels), not real photos of real products; `registry` is **authentic** TTB-approved label artwork from the Public COLA Registry (scripts/make_registry_fixtures.py explains the cases). Ground truth is hand-written in the generators, never taken from the app.

| Engine | Set | Labels | As expected | False pass | False fail | Detection (Fail) | Flagged (not Pass) | Needs review | p50 / p95 round trip | Server p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| azure | clean | 47 | 47/47 (100%) | 0/27 (0%) | 0/20 (0%) | 19/23 (83%) | 23/23 (100%) | 8/43 (19%) | 4.0 s / 4.9 s | 3.7 s / 4.6 s |
| azure | photos | 62 | 60/62 (97%) | 0/36 (0%) | 0/26 (0%) | 26/32 (81%) | 32/32 (100%) | 32/58 (55%) | 4.8 s / 6.6 s | 4.5 s / 6.2 s |
| azure | registry | 67 | 65/67 (97%) | 0/36 (0%) | 0/31 (0%) | 16/24 (67%) | 24/24 (100%) | 39/55 (71%) | 5.6 s / 7.9 s | 5.2 s / 7.6 s |
| local | clean | 48 | 48/48 (100%) | 0/28 (0%) | 0/20 (0%) | 18/24 (75%) | 24/24 (100%) | 26/44 (59%) | 0.7 s / 1.0 s | 0.5 s / 0.6 s |
| local | photos | 62 | 60/62 (97%) | 0/36 (0%) | 2/26 (8%) | 24/32 (75%) | 32/32 (100%) | 32/58 (55%) | 1.3 s / 2.1 s | 1.0 s / 1.7 s |
| local | registry | 68 | 50/68 (74%) | 0/36 (0%) | 16/32 (50%) | 16/24 (67%) | 24/24 (100%) | 24/56 (43%) | 1.4 s / 3.3 s | 1.0 s / 2.9 s |

False pass counts violations *and* labels whose right answer is Needs review. Needs review is over labels whose right answer is Pass or Fail.

- azure / clean: 1 errors; tokens: 90,362 in / 8,789 out over 47 labels = $0.055 ($0.0012 per label at list price).
- azure / photos: tokens: 118,294 in / 12,450 out over 62 labels = $0.074 ($0.0012 per label at list price).
- azure / registry: 1 errors; tokens: 170,805 in / 25,451 out over 67 labels = $0.120 ($0.0018 per label at list price).


## Authentic registry labels: what was tested and what it found

**Source.** 21 records from TTB's Public COLA Registry (approved 1–4 Sep 2026; ttbonline.gov, public pages only), 37 label images, downloaded unchanged (`scripts/fetch_registry_images.py`; SHA-256 in `tests/fixtures/registry/SHA256SUMS`). The artwork is not committed. Mix: bourbon, vodka, gin, rum, brandy, tequila, flavored and imported wine, sake, beer cans, keg collars, a vodka cocktail; 7 imports; 11 records with front and back labels. Each case links to its registry record.

**Expected results were set by hand before any run**, by reading every image and zooming into each warning. Brand comes from the COLA form; ABV and net contents are not on the form, so they were read from the artwork; class/type is the statement printed on the label (TTB's class code is recorded per case).

**34 cases:** 21 as filed; 5 with only the front or display panel and "every side" not ticked (right answer: Needs review); 8 with the untouched artwork and one application field deliberately wrong (ABV, net contents, brand, country, an ABV printed for a different product on a shared keg collar).

**TTB approval is not proof of compliance.** Five approved labels deviate from the rules and were scored as such:
- Cave City rum: warning reads "impairs **yovur** ability".
- Isolation Proof gin: "the **risks** of birth defects".
- Clearwater Light can: "**durring**", "**risks**", and "drive a car or" missing (sideways, about 6 px type).
- Woodson whiskey: class statement "KENTUCKY **BOUBON** WHISKEY".
- Daily Brewing keg: the comma in "machinery, and" is missing (punctuation only: a reviewer's call).

**First run, on the build deployed before this work (d1ba276), 1 repetition, cloud engine:** 0 false passes, but **12 of 16 compliant approved labels were Fail**, and 3 of 5 front-only cases. Causes, each fixed with tests (no safeguard against false passes was relaxed):

| Cause | Fix |
|---|---|
| Warning body printed in capitals failed the case-sensitive comparison (most approved labels do this; 27 CFR 16.22 sets the case of the heading only) | A body entirely in capitals is compared in capitals; a mixed-case body stays case-sensitive |
| The model judged bold wrongly in both directions (regular capitals "bold", bold headings "not bold") and its word alone produced Fail | A bold Fail, like a bold Pass, needs the stroke measurement to agree; the measurement counts only on one printed line read confidently by the offline OCR |
| "GOVERNMENT WARNING :" (space before the colon) reported as a heading problem | Spacing only |
| "(1)According" (no space) counted as a wording change | Spacing only, for every reader |
| Complete warning followed by "CONTAINS SULFITES" counted as added words | Needs review (separate statement or not is a visual question) |
| Net contents in pints and gallons not recognized (malt beverages, 27 CFR 7.70) | U.S. units added |
| Keg collars with several sizes or strengths: the reader picked one | Several sizes: Needs review if the application's is printed; several strengths: Needs review, never Pass |
| Country: "Product of Korea", "Sake of Japan", "Hecho en República Dominicana", "BOLOGNA-ITALIA", a sentence read as a country | Korea alias; foreign or unusual statements are Needs review; a different country in an English statement is still Fail |
| Producer name in the logo, address printed sideways and not read | Name found, address not read: Needs review |
| Text-heavy labels hit the 8 s cloud timeout | 12 s timeout; long marketing paragraphs abbreviated in the transcript |

**Result after the fixes (table above, build a56bae2, 2 repetitions):** cloud engine 0 false passes and 0 false fails on authentic artwork; every violation flagged; 14 of 16 wrong-application checks Fail. Remaining weaknesses, measured:

- **No compliant authentic label passes outright with the cloud engine.** All are Needs review, mainly because bold cannot be confirmed (the model's judgment is unreliable and the stroke measurement does not separate bold from regular on real artwork: approved bold headings measured 0.96–1.36), and because real producer statements carry more than the application value (street, ZIP, "for Kentucky Senator Spirits") and are shown for review. The tool still sorts the work: in this set the reviewer's attention goes to the flagged field, with the reason.
- **Readers correct misspellings.** Both readers read "BOUBON" as "BOURBON", so the class/type field passed (the label was Needs review overall for other reasons). The cloud model also read "yovur" as "your"; the offline cross-check caught that one (Needs review). Letter-level misspellings in large decorative type are a reader limitation that rules cannot see.
- **Offline OCR on real artwork** fails 16 of 32 compliant checks (stylized fonts, sideways text, light-on-dark print it cannot find). It never passed a violation. It is the fallback, not the recommended engine for authentic artwork.
- **Cloud latency on authentic artwork** is 5.6 s typical, 7.9 s for the slowest 5% (more text per label than the synthetic sets).

## Authentic registry labels: by kind of case

| Engine | Kind | Checks | Pass | Needs review | Fail | False pass | False fail |
|---|---|---|---|---|---|---|---|
| azure | Untouched artwork, one application field wrong | 16 | 0 | 2 | 14 | 0 | 0 |
| azure | As filed (approved artwork, every image) | 41 | 0 | 39 | 2 | 0 | 0 |
| azure | Front or display panel only, 'every side' not ticked | 10 | 0 | 10 | 0 | 0 | 0 |
| local | Untouched artwork, one application field wrong | 16 | 0 | 2 | 14 | 0 | 0 |
| local | As filed (approved artwork, every image) | 42 | 0 | 22 | 20 | 0 | 16 |
| local | Front or display panel only, 'every side' not ticked | 10 | 0 | 10 | 0 | 0 | 0 |

Front-only cases are Needs review by design; a Fail there means something visible on the front panel was judged wrong.

**Field-level false passes** (a field that must not pass, passed; the label's overall verdict in brackets):

- azure / woodson_whiskey / class_type: 2 of 2 runs (overall: needs_review, needs_review). Approved front label reads 'KENTUCKY BOUBON WHISKEY' (misspelled class statement); ABV line is ~8 px.
- local / woodson_whiskey / class_type: 2 of 2 runs (overall: needs_review, needs_review). Approved front label reads 'KENTUCKY BOUBON WHISKEY' (misspelled class statement); ABV line is ~8 px.

1 registry requests returned an error (counted in the summary above).

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
| azure | clean | warning_missing_colon | violation | fail | fail |  |
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
| azure | photos | import_no_country_photo | violation | fail, fail | fail |  |
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
| azure | registry | carbliss_cocktail | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | cascahuin_tequila | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | cascahuin_wrong_abv | violation | needs_review, needs_review | fail/needs_review |  |
| azure | registry | cave_city_rum | violation | needs_review, needs_review | fail/needs_review |  |
| azure | registry | clearwater_light_pilsner | violation | fail, fail | fail/needs_review |  |
| azure | registry | crazy_turtle_keg | compliant | needs_review | pass/needs_review |  |
| azure | registry | crazy_turtle_other_products_abv | violation | fail, fail | fail/needs_review |  |
| azure | registry | daily_brewing_lager | review | needs_review, needs_review | fail/needs_review |  |
| azure | registry | granny_gs_wine | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | granny_gs_wrong_net | violation | fail, fail | fail/needs_review |  |
| azure | registry | holy_city_vodka | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | holy_city_wrong_abv | violation | fail, fail | fail/needs_review |  |
| azure | registry | isolation_proof_gin | violation | needs_review, needs_review | fail/needs_review |  |
| azure | registry | kuheiji_sake | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | kuheiji_sake_front_only | review | needs_review, needs_review | needs_review |  |
| azure | registry | lucent_citron | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | lucent_citron_front_only | review | needs_review, needs_review | needs_review |  |
| azure | registry | lucent_wrong_brand | violation | fail, fail | fail/needs_review |  |
| azure | registry | mount_holly_ipa | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | mount_holly_wrong_net | violation | fail, fail | fail/needs_review |  |
| azure | registry | pegau_red_wine | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | pegau_white_wine | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | pegau_white_wine_front_only | review | needs_review, needs_review | needs_review |  |
| azure | registry | seelbachs_bourbon_50ml | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | siboney_rum_import | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | siboney_rum_import_front_only | review | needs_review, needs_review | needs_review |  |
| azure | registry | siboney_wrong_country | violation | fail, fail | fail/needs_review |  |
| azure | registry | sterling_vodka | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | sterling_wrong_net | violation | fail, fail | fail/needs_review |  |
| azure | registry | sun_king_keg | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | thoroughbred_bourbon | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | thoroughbred_bourbon_front_only | review | needs_review, needs_review | needs_review |  |
| azure | registry | villa_zarri_brandy | compliant | needs_review, needs_review | pass/needs_review |  |
| azure | registry | woodson_whiskey | violation | needs_review, needs_review | fail/needs_review | class_type: ['pass', ['fail', 'needs_review']] |
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
| local | photos | beer_blackletter | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_angled | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_curved | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_front_back | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_glare_side | compliant | fail, fail **FALSE FAIL** | needs_review |  |
| local | photos | bourbon_glare_warning | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_small_photo | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_soft_focus | compliant | needs_review, needs_review | needs_review |  |
| local | photos | bourbon_tiny_warning | compliant | needs_review, needs_review | needs_review |  |
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
| local | photos | warning_title_case_curved | violation | needs_review, needs_review | fail/needs_review |  |
| local | photos | wine_script_front_back | compliant | needs_review, needs_review | needs_review |  |
| local | registry | carbliss_cocktail | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | cascahuin_tequila | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | cascahuin_wrong_abv | violation | needs_review, needs_review | fail/needs_review |  |
| local | registry | cave_city_rum | violation | needs_review, needs_review | fail/needs_review |  |
| local | registry | clearwater_light_pilsner | violation | needs_review, needs_review | fail/needs_review |  |
| local | registry | crazy_turtle_keg | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | crazy_turtle_other_products_abv | violation | fail, fail | fail/needs_review |  |
| local | registry | daily_brewing_lager | review | fail, fail | fail/needs_review |  |
| local | registry | granny_gs_wine | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | granny_gs_wrong_net | violation | fail, fail | fail/needs_review |  |
| local | registry | holy_city_vodka | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | holy_city_wrong_abv | violation | fail, fail | fail/needs_review |  |
| local | registry | isolation_proof_gin | violation | fail, fail | fail/needs_review |  |
| local | registry | kuheiji_sake | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | kuheiji_sake_front_only | review | needs_review, needs_review | needs_review |  |
| local | registry | lucent_citron | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | lucent_citron_front_only | review | needs_review, needs_review | needs_review |  |
| local | registry | lucent_wrong_brand | violation | fail, fail | fail/needs_review |  |
| local | registry | mount_holly_ipa | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | mount_holly_wrong_net | violation | fail, fail | fail/needs_review |  |
| local | registry | pegau_red_wine | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | pegau_white_wine | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | pegau_white_wine_front_only | review | needs_review, needs_review | needs_review |  |
| local | registry | seelbachs_bourbon_50ml | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | siboney_rum_import | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | siboney_rum_import_front_only | review | needs_review, needs_review | needs_review |  |
| local | registry | siboney_wrong_country | violation | fail, fail | fail/needs_review |  |
| local | registry | sterling_vodka | compliant | needs_review, needs_review | pass/needs_review |  |
| local | registry | sterling_wrong_net | violation | fail, fail | fail/needs_review |  |
| local | registry | sun_king_keg | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | thoroughbred_bourbon | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | thoroughbred_bourbon_front_only | review | needs_review, needs_review | needs_review |  |
| local | registry | villa_zarri_brandy | compliant | fail, fail **FALSE FAIL** | pass/needs_review |  |
| local | registry | woodson_whiskey | violation | needs_review, needs_review | fail/needs_review | class_type: ['pass', ['fail', 'needs_review']] |

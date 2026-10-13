#!/usr/bin/env python3
"""Write the authentic-label fixtures (tests/fixtures/registry/*.json) from TTB's Public COLA Registry.

The label images are real, TTB-approved artwork. They are not committed: third-party artwork stays
on TTB's site; scripts/fetch_registry_images.py downloads it unchanged into
tests/fixtures/registry/images/ (git-ignored).

Where each application field comes from (the COLA form, TTB F 5100.31, has no alcohol or net
contents field, and its class/type is TTB's code, not the label's wording):

  brand_name              item 6 of the public COLA form
  class_type              the class/type statement printed on the label (TTB's code noted per case)
  alcohol_content         read from the artwork by hand
  net_contents            read from the artwork by hand
  producer_name_address   the name and city on the label's bottler/importer statement; it is the
                          COLA applicant or the DBA the form marks "used on label"
  country / is_import     item 3 (source of product) and the label's country statement

Ground truth was set by reading every image by hand (zooming into the warning) before any run.
Three kinds of case:

  as_filed               the record as approved. Most are compliant. On five approved labels the
                         artwork appears to differ from the rules (warning wording, a misspelled
                         class statement). These are potential findings from reading the public
                         images, not confirmed by TTB, and need independent confirmation; they are
                         scored as "must not Pass" (Needs review or Fail).
  front_only             only the front image, "every side" not ticked: a warning on the back
                         cannot be seen, so the right answer is Needs review, never Fail.
  altered_application    the same untouched images, with one application field deliberately
                         wrong (as a mistyped or mismatched application would be): must not Pass.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "registry"
REGISTRY = "https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid={}"

OK = ["pass", "needs_review"]          # compliant: anything but Fail
NOT_PASS = ["fail", "needs_review"]    # deviation: anything but Pass


def app(brand, class_type, abv, net, producer, bev="spirits", country=None):
    return {"brand_name": brand, "class_type": class_type, "alcohol_content": abv, "net_contents": net,
            "producer_name_address": producer, "country_of_origin": country, "is_import": bool(country),
            "beverage_type": bev}


# ttb_id, image numbers in registry order, notes
RECORDS = {
    "seelbachs_bourbon_50ml": dict(
        ttb_id="26236001000188", images=[1], class_code="101 STRAIGHT BOURBON WHISKY",
        application=app("SEELBACH'S", "Kentucky Straight Bourbon Whiskey", "50% Alc/Vol (100 Proof)", "50 mL",
                        "Seelbach's Spirits, LLC, Jacksonville, FL"),
        truth="compliant", note="Single 50 mL wrap label; the warning is printed sideways (rotated 90 degrees)."),
    "thoroughbred_bourbon": dict(
        ttb_id="26236001000530", images=[1, 2], class_code="101 STRAIGHT BOURBON WHISKY",
        application=app("THOROUGHBRED LEGACY SERIES", "Kentucky Straight Bourbon Whiskey",
                        "56.5% Alc./Vol. (113 Proof)", "750 mL", "Potter Jane Distilling Company, Springfield, Kentucky"),
        truth="compliant", note="Front + back; warning, net contents and bottler on the back."),
    "sterling_vodka": dict(
        ttb_id="26223001000122", images=[1], class_code="301 VODKA 80-89 PROOF",
        application=app("STERLING & CO.", "Vodka", "40% Alc/Vol", "750 mL", "Wight & Co. Distillers, Bardstown, KY"),
        truth="compliant", note="Very wide wrap label (2708x398); warning heading bold, body mixed case."),
    "isolation_proof_gin": dict(
        ttb_id="26226001000267", images=[1, 2, 3, 4], class_code="210 GIN",
        application=app("ISOLATION PROOF", "Gin", "45% Alc/Vol", "750 mL", "Isolation Proof, Bloomville, N.Y."),
        truth="violation", fields={"government_warning": NOT_PASS},
        note="Approved back label reads 'because of the RISKS of birth defects' (required: 'risk')."),
    "cave_city_rum": dict(
        ttb_id="26232001000220", images=[1, 2], class_code="410 U.S. RUM (GOLD)",
        application=app("CAVE CITY DISTILLING CO. RUM", "Rum", "46.5% Alc. By Vol. (93 Proof)", "750 mL",
                        "Cave City Distilling Co., Smiths Grove, KY"),
        truth="violation", fields={"government_warning": NOT_PASS},
        note="Approved label reads 'impairs YOVUR ability' (one-letter typo): a reader that autocorrects would pass it."),
    "holy_city_vodka": dict(
        ttb_id="26229001000351", images=[1], class_code="301 VODKA 80-89 PROOF",
        application=app("HOLY CITY", "Vodka", "40% Alc./Vol. (80 Proof)", "750 mL",
                        "Holy City Brewing, North Charleston, S.C."),
        truth="compliant", note="Clean flat artwork."),
    "siboney_rum_import": dict(
        ttb_id="26208001000603", images=[1, 2], class_code="497 DILUTED RUM GOLD FB",
        application=app("SIBONEY", "Diluted Rum", "34% Alc/Vol", "700 mL", "Vinaio Imports, Bronx, NY",
                        country="Dominican Republic"),
        truth="compliant", note="Import; condensed type on a striped dark background."),
    "villa_zarri_brandy": dict(
        ttb_id="26197001000702", images=[1, 2], class_code="561 ITALIAN GRAPE BRANDY FB",
        application=app("VILLA ZARRI", "Italian Brandy", "53% Alc. by Vol.", "700 mL",
                        "Small Victories Imports, Manhasset, NY", country="Italy"),
        truth="compliant", note="Low resolution (back label 319x653): the warning is ~5 px type, hyphenated 'PREG-NANCY'."),
    "cascahuin_tequila": dict(
        ttb_id="26225001000607", images=[1, 2, 3], class_code="977 TEQUILA FB",
        application=app("CASCAHUIN", "Tequila Blanco", "49% Alc./Vol.", "750 mL",
                        "Connoisseur Wines USA, Inc, Port Washington, NY", country="Mexico"),
        truth="compliant",
        note="Hand-lettered font; label spells CASCAHUÍN (accent); importer and warning on a separate strip."),
    "pegau_white_wine": dict(
        ttb_id="15065001000389", images=[1, 2], class_code="81 TABLE WHITE WINE",
        application=app("DOMAINE DU PEGAU", "White Wine", "14% Alc/Vol", "750 mL", "T. Elenteny Imports, New York, NY",
                        bev="wine", country="France"),
        truth="compliant", note="Import strip carries the US statements; front is French."),
    "pegau_red_wine": dict(
        ttb_id="10334001000372", images=[1, 2, 4, 5], class_code="88 DESSERT /PORT/SHERRY/(COOKING) WINE",
        application=app("DOMAINE DU PEGAU", "Red Wine", "16% Alc. by Vol.", "750 mL", "T Elenteny Imports, New York, NY",
                        bev="wine", country="France"),
        truth="compliant",
        note="Five registry images; the neck label (image 3, vintage only) is left out to stay within 4 per check."),
    "granny_gs_wine": dict(
        ttb_id="25150001000167", images=[1], class_code="82 TABLE FLAVORED WINE",
        application=app("GRANNY G'S WINE CO.", "Elderberry, Apple, Grape, Pear Wine with Natural Flavors",
                        "10.5% Alcohol by Volume", "500 mL", "Granny G's Wine Co., Conroe, TX", bev="wine"),
        truth="compliant", note="Light text on black; bottler line misspelled 'PRODUCDED AND BOTTLED BY' (not a mandatory phrase)."),
    "clearwater_light_pilsner": dict(
        ttb_id="26205001000196", images=[1], class_code="901 BEER",
        application=app("CLEARWATER LIGHT", "Pilsner", "4.2% Alc/Vol", "16 fl oz",
                        "Clearwater Brewing Company, Clearwater, FL", bev="beer"),
        truth="violation", fields={"government_warning": NOT_PASS},
        note="Approved can: sideways ~6 px warning reads 'durring', 'risks', and omits 'drive a car or'."),
    "mount_holly_ipa": dict(
        ttb_id="26190001000603", images=[1], class_code="902 ALE",
        application=app("MOUNT HOLLY BEER", "Hazy IPA", "7.2% Alc by Vol", "1 Pint",
                        "Mount Holly Beer, Beacon, NY", bev="beer"),
        truth="compliant", note="Net contents '1 PINT'; sideways grey warning."),
    "sun_king_keg": dict(
        ttb_id="26189001000102", images=[1], class_code="906 MALT BEVERAGES SPECIALITIES - FLAVORED",
        application=app("SUN KING BREWERY", "Barrel-Aged Maibock Lager", "11.2% Alc. by Vol.", "15.5 gallons",
                        "Sun King Brewery, Indianapolis, IN", bev="beer"),
        truth="compliant", note="Keg collar: net contents are tick boxes (5.16 / 15.5 gallons), neither ticked in the artwork."),
    "crazy_turtle_keg": dict(
        ttb_id="26224001000266", images=[1], class_code="902 ALE",
        application=app("CRAZY TURTLE", "Hazy India Pale Ale", "6.5% Alc./Vol.", "15.5 U.S. Gallons",
                        "Clearwater Brewing Company, Clearwater, FL", bev="beer"),
        truth="compliant", note="Shared keg collar: three products with three strengths, the right one ticked."),
    "daily_brewing_lager": dict(
        ttb_id="26219001000007", images=[1], class_code="956 MALT BEVERAGES SPECIALITIES",
        application=app("DAILY BREWING", "Ginseng Lager", "4.5% Alc/Vol", "5.28 U.S. Gallons (20 L)",
                        "QQD Corporation, Brea, CA", bev="beer", country="South Korea"),
        truth="review", fields={"government_warning": NOT_PASS},
        note="Warning omits the comma in 'machinery, and': punctuation only, a reviewer's call. Label says 'Product of Korea'."),
    "carbliss_cocktail": dict(
        ttb_id="26056001000136", images=[1], class_code="643 VODKA SPECIALTIES",
        application=app("CARBLISS", "Vodka Cocktail", "5% Alc/Vol", "12 fl oz", "SNFood & Beverage LLC, Verona, WI"),
        truth="compliant", note="Brand only in a script logo; warning sideways."),
    "woodson_whiskey": dict(
        ttb_id="26218001000660", images=[1, 2], class_code="641 WHISKY SPECIALTIES",
        application=app("WOODSON", "Kentucky Bourbon Whiskey Finished with Port Staves", "57% Alc/Vol (114 Proof)",
                        "750 mL", "Kettner Distillery LLC, San Diego, CA"),
        truth="violation", fields={"class_type": NOT_PASS},
        note="Approved front label reads 'KENTUCKY BOUBON WHISKEY' (misspelled class statement); ABV line is ~8 px."),
    "lucent_citron": dict(
        ttb_id="26222001000393", images=[1, 2], class_code="643 VODKA SPECIALTIES",
        application=app("LUCENT", "Vodka with Natural Flavors", "30% Alcohol per Volume (60 Proof)", "1 Liter",
                        "Sazerac Co., Louisville, KY"),
        truth="compliant", note="Front + back."),
    "kuheiji_sake": dict(
        ttb_id="26216001000640", images=[1, 2], class_code="981 SAKE - IMPORTED",
        application=app("KUHEIJI", "Sake", "15% Alc./Vol.", "720 mL", "Kuheiji USA, Manhasset, NY", bev="wine",
                        country="Japan"),
        truth="compliant", note="Front is Japanese calligraphy; English statements on the back. 'GOVERNMENT WARNING :' spaced."),
}

FRONT_ONLY = {  # case -> image numbers of the front alone
    "thoroughbred_bourbon": [1], "siboney_rum_import": [2], "lucent_citron": [1],
    "pegau_white_wine": [2], "kuheiji_sake": [2],
}

ALTERED = {  # new case -> (base case, field, wrong value, why)
    "holy_city_wrong_abv": ("holy_city_vodka", "alcohol_content", "45% Alc./Vol. (90 Proof)", "label says 40% / 80 proof"),
    "sterling_wrong_net": ("sterling_vodka", "net_contents", "1 Liter", "label says 750 mL"),
    "lucent_wrong_brand": ("lucent_citron", "brand_name", "LUMINA", "label says LUCENT"),
    "siboney_wrong_country": ("siboney_rum_import", "country_of_origin", "Mexico", "label says Dominican Republic"),
    "granny_gs_wrong_net": ("granny_gs_wine", "net_contents", "750 mL", "label says 500 mL"),
    "cascahuin_wrong_abv": ("cascahuin_tequila", "alcohol_content", "40% Alc./Vol.", "label says 49%"),
    "crazy_turtle_other_products_abv": ("crazy_turtle_keg", "alcohol_content", "4.2% Alc./Vol.",
                                       "4.2% is printed on the collar, but for an unticked product"),
    "mount_holly_wrong_net": ("mount_holly_ipa", "net_contents", "12 fl oz", "label says 1 pint"),
}


def case(name, rec, kind, images, all_sides, application, truth, allowed, fields, note):
    return {
        "case": name, "kind": kind, "authentic": True, "truth": truth,
        "description": note,
        "source": {"registry": "TTB Public COLA Registry", "ttb_id": rec["ttb_id"], "url": REGISTRY.format(rec["ttb_id"]),
                   "class_code": rec["class_code"], "registry_images": images},
        "images": [f"images/{rec['ttb_id']}_{n}" for n in images],  # extension resolved at fetch time
        "all_sides": all_sides, "application": application,
        "expected": {e: {"overall": allowed, "fields": fields} for e in ("azure_vision", "local_ocr")},
    }


def build() -> dict[str, dict]:
    out = {}
    for name, r in RECORDS.items():
        allowed = OK if r["truth"] == "compliant" else NOT_PASS
        out[name] = case(name, r, "as_filed", r["images"], True, r["application"], r["truth"], allowed,
                         r.get("fields", {}), r["note"])
    for base, imgs in FRONT_ONLY.items():
        r = RECORDS[base]
        out[base + "_front_only"] = case(
            base + "_front_only", r, "front_only", imgs, False, r["application"], "review", ["needs_review"],
            {"government_warning": "needs_review"},
            "Front image only, 'every side' not ticked: the warning is on the back image, which was not supplied.")
    for name, (base, field, value, why) in ALTERED.items():
        r = RECORDS[base]
        a = dict(r["application"], **{field: value})
        if field == "country_of_origin":
            a["is_import"] = True
        out[name] = case(name, r, "altered_application", r["images"], True, a, "violation", NOT_PASS,
                         {field: NOT_PASS}, f"Untouched registry images; application {field} set to {value!r} ({why}).")
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, c in build().items():
        (OUT / f"{name}.json").write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(build())} cases to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

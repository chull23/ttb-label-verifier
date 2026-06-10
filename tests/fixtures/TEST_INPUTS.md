# Test Label Inputs

For each label below, enter these values into the sidebar before clicking Verify.
The **Application Value** column is what you type — it represents the COLA form.

---

## label_01_pass.png — Expected: PASS ✅

All fields match exactly.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Bottler Name & Address | `Old Tom Distillery, Louisville, KY 40201` |
| Country of Origin | `Product of USA` |
| Government Warning | *(leave as pre-filled default)* |

---

## label_02_fail_gov_warning.png — Expected: FAIL ❌

The label has `Government Warning:` in title case instead of `GOVERNMENT WARNING:` in all caps.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** The Government Warning field should show FAIL with a note about the all-caps header requirement.

---

## label_03_fail_abv.png — Expected: FAIL ❌

The label shows 40% ABV / 80 Proof, but the application says 45%.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** The Alcohol Content field should show FAIL with the numeric difference noted.

---

## label_04_fail_brand.png — Expected: FAIL ❌

The label says `RIVER BEND SPIRITS` but the application says `OLD TOM DISTILLERY`.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Brand Name should show FAIL with a low similarity score.

---

## label_05_warning_brand.png — Expected: WARNING ⚠️

The label says `Old Tom Distilleries` (plural) vs `OLD TOM DISTILLERY` — close but not exact.
This exercises the fuzzy match threshold and the Dave Morrison "judgment call" case.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Brand Name should show WARNING (not FAIL) with a similarity percentage and a note to review manually.

---

## label_06_fail_proof_wrong.png — Expected: FAIL ❌

Label shows `45% Alc./Vol. (80 Proof)` — 45 × 2 = 90, not 80.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Proof Consistency should FAIL — 80 Proof stated but 90 expected.

---

## label_07_fail_below_min_abv.png — Expected: FAIL ❌

Label shows `38% Alc./Vol. (76 Proof)` — below the 40% minimum for distilled spirits.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Minimum ABV should FAIL — 38% is below the 40% floor (27 CFR 5.143(a)).

---

## label_08_fail_bourbon_from_canada.png — Expected: FAIL ❌

Label shows `Product of Canada` — bourbon is a distinctive product of the USA only.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Country of Origin | `Product of USA` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Bourbon — US Origin Required should FAIL (27 CFR 5.143(b)).

---

## label_09_fail_straight_with_additives.png — Expected: FAIL ❌

Label shows `Contains Natural Flavors` — straight bourbon may not contain any additives.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** No Additives (Straight Designation) should FAIL (27 CFR 5.143, Table 1, row 5).

---

## label_10_warn_kentucky_wrong_state.png — Expected: WARNING ⚠️

Label shows bottler in Nashville, TN — class/type says "Kentucky" but address is not in KY.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Bottler Name & Address | `Old Tom Distillery, Louisville, KY 40201` |
| Government Warning | *(leave as pre-filled default)* |

**What to look for:** Kentucky Geographical Designation should WARNING — TN address detected, flagged for manual production record review.

---

## label_11_fail_missing_age_statement.png — Expected: FAIL ❌

No age statement on label, but the application declares a 2-year-old product. Age must be shown for straight whisky under 4 years.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**Important:** Also set **Product Age** to `2` in the sidebar before verifying.

**What to look for:** Age Statement should FAIL — 2-year-old straight whisky must display age (27 CFR 5.74).

---

## label_12_pass_age_statement.png — Expected: PASS ✅

Same 2-year-old product, but this label correctly shows `Aged 2 Years`.

| Field | Enter this value |
|---|---|
| Brand Name | `OLD TOM DISTILLERY` |
| Class / Type | `Kentucky Straight Bourbon Whiskey` |
| Alcohol Content | `45% Alc./Vol. (90 Proof)` |
| Net Contents | `750 mL` |
| Government Warning | *(leave as pre-filled default)* |

**Important:** Also set **Product Age** to `2` in the sidebar before verifying.

**What to look for:** All fields including Age Statement should PASS.

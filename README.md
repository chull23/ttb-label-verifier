# TTB AI Label Verifier

AI-powered alcohol label verification prototype for the TTB Compliance Division.

## Quick start

```bash
# 1. Clone and enter the directory
git clone <your-repo-url>
cd ttb-label-verifier

# 2. Create and activate a virtual environment (requires Python 3.10+)
python3.10 -m venv .venv        # or python3.11/3.12/3.13, etc.
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 5. Run the app
.venv/bin/streamlit run app.py
```

The app opens at http://localhost:8501 if run locally.

## Login
The app has simple password protection because it's in a public space and each API call to Anthropic costs money.

**Creds**: admin/TTBGOV1!

## Usage

**Single label:** upload one image, fill in the COLA fields in the sidebar, and click Verify.

**Batch upload:** switch to the Batch Upload tab, upload multiple images or a ZIP archive, fill in the sidebar, and click Run Batch Verification. Results update in real time. Download a CSV summary when done.

## Project structure

```
app.py          Streamlit UI
verifier.py     Core verification service (sync)
batch.py        Async batch orchestration
rules.py        Deterministic field-matching rules (no API calls)
models.py       Dataclasses: FieldResult, LabelResult, ApplicationData
exceptions.py   Typed exception hierarchy
prompt.py       Claude prompt templates
config.py       Settings from .env
requirements.txt
.env.example
```

## Running tests

```bash
pip install pytest
pytest tests/
```

Tests in `tests/test_rules.py` cover all field-matching rules without any API calls.

## Configuration

See `.env.example` for all available settings. The most important:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Model for vision extraction |
| `API_TIMEOUT_SECONDS` | `20` | Hard timeout per label |
| `MAX_CONCURRENT` | `5` | Batch concurrency cap |
| `BRAND_NAME_PASS_THRESHOLD` | `0.92` | Fuzzy match ratio for PASS |
| `CONFIDENCE_THRESHOLD` | `0.70` | Below this = image quality warning |
| `USER` | — | If set (with `USER_PASS`), requires login with this username |
| `USER_PASS` | — | Password for `USER`. Login is disabled if either is unset |

## Approach

1. **Extraction (Claude, vision):** the uploaded label image is sent to Claude with a prompt (`prompt.py`) that asks it to extract label fields verbatim as JSON — brand name, class/type, alcohol content, net contents, government warning, bottler/address, country of origin, age statement, additives, appellation, vintage, sulfite/aspartame/color-additive statements, etc. Claude only extracts; it makes no compliance judgments.
2. **Deterministic rules (no API calls):** `rules.py` compares the extracted label values against the COLA application fields entered in the sidebar and applies TTB regulatory checks (27 CFR Parts 4, 5, and 7) — e.g. brand name match, government warning verbatim text, ABV/proof consistency, minimum bottling proof, Bottled in Bond, Bourbon/Kentucky designations, sulfite declarations, appellation/varietal rules, standard of fill, and beer additive declarations.
3. **Beverage-type routing:** the relevant ruleset (distilled spirits / wine / beer) is auto-detected from the label's class/type, with a manual override in the sidebar.
4. **UI:** a Streamlit app with single-label and batch (ZIP/multi-file) modes. Verification runs only on button click to avoid unnecessary API spend. Results are shown as color-coded, stacked field cards; batch results can be exported as CSV.

## Tools used

- **Python 3.10+** — required for `X | None` type-union syntax used throughout.
- **Streamlit** — web UI, file upload, sidebar form, session state.
- **Anthropic Claude API** (`claude-opus-4-8` by default) — vision-based field extraction from label images.
- **Pillow (PIL)** — image validation and downscaling/recompression to stay under the API's image size limit.
- **pandas** — CSV export of batch results.
- **pytest** — unit tests for `rules.py` (no API calls required).
- **python-dotenv** — loads `.env` for local config; falls back to Streamlit `st.secrets` when deployed.

## Assumptions

- This is a **prototype**, not a certified compliance tool — results are meant to assist, not replace, human reviewers.
- All label text is assumed to be in **English** (per TTB requirements); non-English labels are not specially handled.
- COLA application data is entered manually via the sidebar; there is no integration with TTB's COLA system.
- A single label image is assumed to show all the relevant mandatory text (front/back panels combined into one image, or the most informative panel).
- Checks that can't be verified from an image alone are explicitly out of scope, e.g.: distillation proof ≤ 160°, mash bill composition, charred-new-oak barrel requirements, minimum 2-year aging for "straight" spirits, single-distillery/single-season/bonded-warehouse provenance for Bottled in Bond, and import-country-of-origin rules for beer.
- Mandatory information printed only on a cap, cork, foil capsule, or container bottom (which TTB prohibits as the sole location) is not separately detected.
- Confidence scores from Claude are used as a signal for `NEEDS_REVIEW`/low-confidence flags, not as a substitute for the deterministic rule checks.

## TTB requirements reference

- [27 CFR Part 16](https://www.ecfr.gov/current/title-27/chapter-I/subchapter-A/part-16) — Government Warning Statement

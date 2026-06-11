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

The app opens at http://localhost:8501.

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

## TTB requirements reference

- [TTB Label Approval](https://www.ttb.gov/labeling)
- [27 CFR Part 16](https://www.ecfr.gov/current/title-27/chapter-I/subchapter-A/part-16) — Government Warning Statement

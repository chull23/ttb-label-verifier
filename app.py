"""
app.py
------
Streamlit UI for the TTB AI Label Verification tool.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from dataclasses import asdict

import pandas as pd
import streamlit as st

from batch import process_batch
from config import settings
from exceptions import (
    BatchError,
    ImageError,
    LabelVerificationError,
    PartialBatchError,
)
from models import ApplicationData, LabelResult
from rules import GOVERNMENT_WARNING_TEXT
from verifier import verify_label

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title=settings.app_title,
    page_icon=settings.page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Status colours ─────────────────────────────────────────────────────────────

STATUS_COLOUR = {
    "PASS": "#1a7f37",       # green
    "FAIL": "#cf222e",       # red
    "WARNING": "#9a6700",    # amber
    "NOT_FOUND": "#cf222e",  # treat as fail in colour
    "NEEDS_REVIEW": "#9a6700",
}

STATUS_ICON = {
    "PASS": "✅",
    "FAIL": "❌",
    "WARNING": "⚠️",
    "NOT_FOUND": "❓",
    "NEEDS_REVIEW": "🔍",
}

OVERALL_BG = {
    "PASS": "#dafbe1",
    "FAIL": "#ffebe9",
    "WARNING": "#fff8c5",
    "NEEDS_REVIEW": "#fff8c5",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _application_from_sidebar() -> ApplicationData:
    """Read application data from the sidebar form widgets."""
    return ApplicationData(
        brand_name=st.session_state.get("sb_brand_name", ""),
        class_type=st.session_state.get("sb_class_type", ""),
        alcohol_content=st.session_state.get("sb_alcohol_content", ""),
        net_contents=st.session_state.get("sb_net_contents", ""),
        government_warning=st.session_state.get("sb_gov_warning", ""),
        bottler_name_address=st.session_state.get("sb_bottler", ""),
        country_of_origin=st.session_state.get("sb_country", ""),
        age_statement=st.session_state.get("sb_age_statement", ""),
        beverage_type=st.session_state.get("sb_beverage_type", "distilled_spirits"),
        sulfite_ppm=st.session_state.get("sb_sulfite_ppm", ""),
        vintage_year=st.session_state.get("sb_vintage_year", ""),
        added_flavor_alcohol=st.session_state.get("sb_added_flavor_alcohol", ""),
        color_additives=st.session_state.get("sb_color_additives", ""),
        aspartame_present=st.session_state.get("sb_aspartame_present", ""),
    )


def _render_label_result(result: LabelResult) -> None:
    """Render a single LabelResult as a styled card."""
    overall_bg = OVERALL_BG.get(result.overall, "#f6f8fa")
    icon = STATUS_ICON.get(result.overall, "")

    st.markdown(
        f"""
        <div style="
            background:{overall_bg};
            border-radius:8px;
            padding:12px 16px;
            margin-bottom:8px;
            border-left: 4px solid {STATUS_COLOUR.get(result.overall, '#888')};
        ">
        <strong>{icon} Overall: {result.overall}</strong>
        {"  &nbsp;·&nbsp;  " + result.filename if result.filename else ""}
        &nbsp;·&nbsp; {result.processing_time_ms} ms
        </div>
        """,
        unsafe_allow_html=True,
    )

    if result.error:
        st.error(result.error)
        return

    if not result.fields:
        st.warning("No fields were returned for this label.")
        return

    for f in result.fields:
        bg = OVERALL_BG.get(f.status, "#ffffff")
        border = STATUS_COLOUR.get(f.status, "#888")
        status_label = f"{STATUS_ICON.get(f.status, '')} {f.status}"
        notes_html = (
            f'<div style="margin-top:6px; font-size:0.85em; color:#555;">{f.notes}</div>'
            if f.notes
            else ""
        )
        st.markdown(
            f"""
            <div style="
                background:{bg};
                border-radius:8px;
                padding:10px 14px;
                margin-bottom:6px;
                border-left: 4px solid {border};
            ">
            <div style="display:flex; justify-content:space-between; align-items:baseline;">
                <strong>{f.field_name}</strong>
                <span>{status_label}</span>
            </div>
            <div style="margin-top:6px;">
                <div style="font-size:0.85em; color:#555;">Application Value</div>
                <div>{f.application_value or "—"}</div>
            </div>
            <div style="margin-top:6px;">
                <div style="font-size:0.85em; color:#555;">Label Value</div>
                <div>{f.label_value or "—"}</div>
            </div>
            {notes_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _extract_images_from_upload(uploaded_files) -> list[tuple[str, bytes]]:
    """
    Given a list of Streamlit UploadedFile objects, return (filename, bytes) pairs.
    Handles individual images and ZIP archives.
    """
    images: list[tuple[str, bytes]] = []
    for uf in uploaded_files:
        name = uf.name.lower()
        raw = uf.read()
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in zf.namelist():
                    basename = entry.rsplit("/", 1)[-1]
                    if basename.startswith("._") or basename.startswith("."):
                        continue
                    if "__MACOSX" in entry:
                        continue
                    entry_lower = entry.lower()
                    if any(entry_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
                        images.append((entry, zf.read(entry)))
        else:
            images.append((uf.name, raw))
    return images


def _results_to_csv(results: list[LabelResult]) -> str:
    """Convert batch results to a CSV string for download."""
    rows = []
    for r in results:
        if r.error:
            rows.append(
                {
                    "Filename": r.filename,
                    "Overall": "ERROR",
                    "Field": "",
                    "Application Value": "",
                    "Label Value": "",
                    "Status": "",
                    "Notes": r.error,
                }
            )
        else:
            for f in r.fields:
                rows.append(
                    {
                        "Filename": r.filename,
                        "Overall": r.overall,
                        "Field": f.field_name,
                        "Application Value": f.application_value,
                        "Label Value": f.label_value or "",
                        "Status": f.status,
                        "Notes": f.notes,
                    }
                )
    return pd.DataFrame(rows).to_csv(index=False)


# ── Exception rendering ───────────────────────────────────────────────────────

def _render_exception(exc: LabelVerificationError, retry_key: str | None = None) -> None:
    """Render a LabelVerificationError as a Streamlit error/warning banner."""
    from exceptions import (
        APITimeoutError,
        APIRateLimitError,
        ImageError,
        MalformedResponseError,
        LowConfidenceError,
    )

    if isinstance(exc, (APITimeoutError, APIRateLimitError)):
        st.warning(exc.user_message)
        if retry_key:
            st.button("Retry", key=retry_key)
    elif isinstance(exc, ImageError):
        st.error(exc.user_message)
    elif isinstance(exc, LowConfidenceError):
        st.warning(exc.user_message)
    elif isinstance(exc, MalformedResponseError):
        st.warning(exc.user_message)
    elif isinstance(exc, PartialBatchError):
        st.warning(exc.user_message)
    else:
        st.error(exc.user_message)


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_sidebar() -> None:
    with st.sidebar:
        st.header("COLA Application Fields")
        st.caption(
            "Enter the values from the COLA application form. "
            "Fields you fill will be verified against the label. "
            "Empty fields are skipped."
        )

        st.selectbox(
            "Beverage Type",
            options=["auto", "distilled_spirits", "wine", "beer"],
            format_func=lambda v: {
                "auto": "Auto-detect from label",
                "distilled_spirits": "Distilled Spirits",
                "wine": "Wine",
                "beer": "Beer / Malt Beverage",
            }[v],
            key="sb_beverage_type",
            help="Routes label-specific compliance rules (27 CFR Parts 4, 5, and 7).",
        )

        st.text_input("Brand Name", key="sb_brand_name", placeholder="e.g. OLD TOM DISTILLERY")
        st.text_input("Class / Type", key="sb_class_type", placeholder="e.g. Kentucky Straight Bourbon Whiskey")
        st.text_input("Alcohol Content", key="sb_alcohol_content", placeholder="e.g. 45% Alc./Vol. (90 Proof)")
        st.text_input("Net Contents", key="sb_net_contents", placeholder="e.g. 750 mL")

        with st.expander("Government Warning (click to edit)", expanded=False):
            st.text_area(
                "Government Warning Text",
                value=GOVERNMENT_WARNING_TEXT,
                key="sb_gov_warning",
                height=180,
                help=(
                    "The statutory warning text is pre-filled. "
                    "Edit only if verifying against a non-standard application."
                ),
            )

        st.text_input("Bottler Name & Address", key="sb_bottler", placeholder="Optional — presence check only")
        st.text_input("Country of Origin", key="sb_country", placeholder="Optional — presence check only")
        st.text_input(
            "Age Statement (COLA application)",
            key="sb_age_statement",
            placeholder="e.g. Aged 3 Years — required on label if under 4 years",
        )

        if st.session_state.get("sb_beverage_type") == "wine":
            st.subheader("Wine-specific")
            st.text_input(
                "Sulfite Level",
                key="sb_sulfite_ppm",
                placeholder="e.g. 25 ppm or 0",
            )
            st.text_input(
                "Vintage Year",
                key="sb_vintage_year",
                placeholder="e.g. 2021",
            )

        if st.session_state.get("sb_beverage_type") == "beer":
            st.subheader("Beer-specific")
            st.selectbox(
                "Alcohol from added flavors/ingredients?",
                options=["", "yes", "no"],
                key="sb_added_flavor_alcohol",
                help="If 'yes', a numeric alcohol content statement becomes mandatory.",
            )
            st.text_input(
                "Color Additives",
                key="sb_color_additives",
                placeholder="e.g. FD&C Yellow No. 5, Cochineal Extract",
            )
            st.selectbox(
                "Contains Aspartame?",
                options=["", "yes", "no"],
                key="sb_aspartame_present",
            )

        st.divider()
        st.caption(
            f"Timeout: {settings.api_timeout_seconds:.0f}s  \n"
            f"Batch concurrency: {settings.max_concurrent}"
        )


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_login() -> bool:
    """
    If AUTH_USER/AUTH_PASS (env: USER/USER_PASS) are configured, render a login
    form and return True only once the entered credentials match. Returns True
    immediately if no credentials are configured.
    """
    if not settings.auth_user or not settings.auth_pass:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title(f"{settings.page_icon} {settings.app_title}")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        if username == settings.auth_user and password == settings.auth_pass:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid username or password.")

    return False


# ── Main UI ───────────────────────────────────────────────────────────────────

def main() -> None:
    if not _check_login():
        return

    _render_sidebar()

    st.title(f"{settings.page_icon} {settings.app_title}")
    st.caption(
        "Upload a label image and verify it against the COLA application fields in the sidebar. "
        "For batch processing, upload multiple images or a ZIP archive."
    )

    # API key warning banner (non-blocking)
    if not settings.anthropic_api_key:
        st.error(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file and restart the app."
        )

    tab_single, tab_batch = st.tabs(["Single Label", "Batch Upload"])

    # ── Single label tab ──────────────────────────────────────────────────────
    with tab_single:
        uploaded = st.file_uploader(
            "Upload label image",
            type=["jpg", "jpeg", "png", "webp"],
            key="single_upload",
            help="Supported formats: JPG, PNG, WEBP. Max size: 20 MB.",
        )

        if uploaded is not None:
            col_img, col_result = st.columns([1, 2])

            with col_img:
                st.image(uploaded, caption=uploaded.name, use_container_width=True)

            with col_result:
                application = _application_from_sidebar()

                if not application.has_any_data():
                    st.info(
                        "Fill in at least one COLA application field in the sidebar "
                        "to start verification."
                    )
                else:
                    with st.spinner("Analysing label..."):
                        try:
                            uploaded.seek(0)
                            result = verify_label(
                                image_bytes=uploaded.read(),
                                application=application,
                                filename=uploaded.name,
                            )
                            _render_label_result(result)
                        except LabelVerificationError as exc:
                            _render_exception(exc, retry_key="retry_single")

    # ── Batch upload tab ──────────────────────────────────────────────────────
    with tab_batch:
        st.markdown(
            "Upload multiple label images or a ZIP archive. "
            "All labels are verified against the same COLA application fields in the sidebar."
        )

        uploaded_batch = st.file_uploader(
            "Upload labels (images or ZIP)",
            type=["jpg", "jpeg", "png", "webp", "zip"],
            accept_multiple_files=True,
            key="batch_upload",
        )

        if uploaded_batch:
            images = _extract_images_from_upload(uploaded_batch)

            if not images:
                st.warning("No valid image files found in the upload.")
            else:
                application = _application_from_sidebar()

                if not application.has_any_data():
                    st.info("Fill in COLA fields in the sidebar before running batch verification.")
                else:
                    st.write(f"Found **{len(images)}** label(s). Ready to verify.")

                    if st.button("Run Batch Verification", type="primary"):
                        progress_bar = st.progress(0, text="Starting...")
                        status_placeholder = st.empty()
                        results_placeholder = st.empty()

                        completed_results: list[LabelResult] = []

                        async def on_progress(completed: int, total: int, result: LabelResult) -> None:
                            completed_results.append(result)
                            pct = completed / total
                            icon = STATUS_ICON.get(result.overall, "")
                            progress_bar.progress(
                                pct,
                                text=f"{completed}/{total} — {result.filename} {icon} {result.overall}",
                            )
                            # Live results table
                            rows = []
                            for r in completed_results:
                                rows.append(
                                    {
                                        "File": r.filename,
                                        "Status": f"{STATUS_ICON.get(r.overall, '')} {r.overall}",
                                        "Time (ms)": r.processing_time_ms,
                                        "Error": r.error or "",
                                    }
                                )
                            results_placeholder.dataframe(
                                pd.DataFrame(rows),
                                use_container_width=True,
                                hide_index=True,
                            )

                        partial_error = None
                        all_results: list[LabelResult] = []

                        try:
                            all_results = asyncio.run(
                                process_batch(
                                    images=images,
                                    application=application,
                                    progress_callback=on_progress,
                                )
                            )
                        except PartialBatchError as exc:
                            partial_error = exc
                            all_results = completed_results
                        except LabelVerificationError as exc:
                            _render_exception(exc)
                            st.stop()

                        progress_bar.progress(1.0, text="Complete.")

                        if partial_error:
                            _render_exception(partial_error)

                        # Summary
                        pass_count = sum(1 for r in all_results if r.overall == "PASS")
                        fail_count = sum(1 for r in all_results if r.overall in ("FAIL", "NOT_FOUND"))
                        warn_count = sum(1 for r in all_results if r.overall in ("WARNING", "NEEDS_REVIEW"))

                        col1, col2, col3 = st.columns(3)
                        col1.metric("Pass", pass_count)
                        col2.metric("Fail", fail_count)
                        col3.metric("Review", warn_count)

                        # Expanded results for each label
                        with st.expander("Detailed results", expanded=False):
                            for r in all_results:
                                st.subheader(r.filename or "Label")
                                _render_label_result(r)
                                st.divider()

                        # CSV download
                        csv_data = _results_to_csv(all_results)
                        st.download_button(
                            label="Download results as CSV",
                            data=csv_data,
                            file_name="ttb_batch_results.csv",
                            mime="text/csv",
                        )


if __name__ == "__main__":
    main()

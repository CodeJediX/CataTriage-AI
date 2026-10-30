from pathlib import Path
from datetime import date
import shutil

import pandas as pd
import streamlit as st


# ==========================================================
# PATHS
# ==========================================================

LABEL_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\model1_clinician_label_sheet.csv"
)

BACKUP_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\model1_clinician_label_sheet_BACKUP.csv"
)


# ==========================================================
# PAGE SETTINGS
# ==========================================================

st.set_page_config(
    page_title="CataTriage-AI Labeling",
    page_icon="👁️",
    layout="wide"
)


# ==========================================================
# HELPERS
# ==========================================================

def clean_value(value):
    """
    Convert NaN values to empty strings.
    """

    if pd.isna(value):
        return ""

    return str(value)


def load_data():
    """
    Load clinician label sheet.

    Also:
    - creates one backup if needed
    - safely adds unusable_reason if missing
    """

    if not LABEL_FILE.exists():

        st.error(
            f"Label sheet not found:\n{LABEL_FILE}"
        )

        st.stop()

    # ------------------------------------------------------
    # CREATE ORIGINAL BACKUP ONCE
    # ------------------------------------------------------

    if not BACKUP_FILE.exists():

        shutil.copy2(
            LABEL_FILE,
            BACKUP_FILE
        )

    # ------------------------------------------------------
    # LOAD CSV
    # ------------------------------------------------------

    df = pd.read_csv(
        LABEL_FILE,
        dtype=str
    ).fillna("")

    # ------------------------------------------------------
    # ADD COLUMN IF MISSING
    # ------------------------------------------------------

    if "unusable_reason" not in df.columns:

        df["unusable_reason"] = ""

        df.to_csv(
            LABEL_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    return df


def save_data(df):
    """
    Save the current label sheet.
    """

    df.to_csv(
        LABEL_FILE,
        index=False,
        encoding="utf-8-sig"
    )


# ==========================================================
# LOAD DATA
# ==========================================================

df = load_data()

total_images = len(df)

if total_images == 0:

    st.error(
        "The clinician label sheet contains no images."
    )

    st.stop()


# ==========================================================
# SESSION STATE
# ==========================================================

def find_first_unlabeled_index(dataframe):
    """
    Find the first image that has not yet been reviewed.
    An image is considered reviewed when reviewer_id is filled.
    """

    unlabeled_mask = (
        dataframe["reviewer_id"]
        .astype(str)
        .str.strip()
        .eq("")
    )

    unlabeled_indexes = dataframe.index[
        unlabeled_mask
    ].tolist()

    if len(unlabeled_indexes) == 0:
        return 0

    return int(
        unlabeled_indexes[0]
    )


if "index" not in st.session_state:

    st.session_state.index = (
        find_first_unlabeled_index(df)
    )


if "default_reviewer_id" not in st.session_state:
    st.session_state.default_reviewer_id = ""


# Prevent invalid index
if st.session_state.index < 0:
    st.session_state.index = 0


if st.session_state.index >= total_images:
    st.session_state.index = total_images - 1


index = st.session_state.index

row = df.iloc[index]

registry_id = str(
    row["registry_id"]
)


# ==========================================================
# HEADER
# ==========================================================

st.title(
    "CataTriage-AI — Model 1 Clinician Labeling"
)


# ==========================================================
# SESSION REVIEWER ID
# ==========================================================

st.text_input(
    "Session Reviewer ID",
    key="default_reviewer_id",
    placeholder="Example: OPH_01",
    help=(
        "Enter the reviewer ID once. "
        "It will automatically be reused for every "
        "new image during this session."
    )
)


st.caption(
    "Local labeling tool for cataract detection "
    "and severity review."
)


# ==========================================================
# PROGRESS
# ==========================================================

completed = (
    df["reviewer_id"]
    .astype(str)
    .str.strip()
    .ne("")
    .sum()
)


progress = completed / total_images


st.progress(
    progress
)


st.write(
    f"**Progress:** {completed} / {total_images} labeled"
)


st.write(
    f"**Current image:** {index + 1} / {total_images}"
)


st.divider()


# ==========================================================
# MAIN LAYOUT
# ==========================================================

left, right = st.columns(
    [1.3, 1]
)


# ==========================================================
# LEFT PANEL — IMAGE
# ==========================================================

with left:

    st.subheader(
        "Image"
    )

    image_path = Path(
        row["processed_path"]
    )

    # ------------------------------------------------------
    # DISPLAY IMAGE
    # ------------------------------------------------------

    if image_path.exists():

        st.image(
            str(image_path),
            caption=registry_id,
            use_container_width=True
        )

    else:

        st.error(
            f"Image not found:\n{image_path}"
        )

    # ------------------------------------------------------
    # IMAGE DETAILS
    # ------------------------------------------------------

    st.write(
        f"**Registry ID:** `{registry_id}`"
    )

    st.write(
        f"**Group ID:** `{row['group_id']}`"
    )

    st.write(
        f"**Dataset:** `{row['dataset_component']}`"
    )

    st.write(
        f"**Source:** `{row['source_path']}`"
    )


# ==========================================================
# RIGHT PANEL — CLINICIAN REVIEW
# ==========================================================

with right:

    st.subheader(
        "Clinician Review"
    )

    # ======================================================
    # CURRENT SAVED VALUES
    # ======================================================

    current_usable = clean_value(
        row["clinical_image_usable"]
    )

    current_cataract = clean_value(
        row["cataract_present"]
    )

    current_severity = clean_value(
        row["overall_severity"]
    )

    current_reason = clean_value(
        row["unusable_reason"]
    )


    # ======================================================
    # IMAGE USABILITY
    # ======================================================

    usable_choices = [
        "YES",
        "NO",
        "UNSURE"
    ]

    usable_index = (
        usable_choices.index(
            current_usable
        )
        if current_usable in usable_choices
        else None
    )

    usable = st.radio(
        "Clinical image usable?",
        usable_choices,
        index=usable_index,
        horizontal=True,
        key=f"usable_{registry_id}"
    )


    # ======================================================
    # UNUSABLE / UNCERTAIN REASON
    # ======================================================

    unusable_reason = None

    reason_options = [
        "BLUR",
        "TOO_DARK",
        "TOO_BRIGHT",
        "LENS_NOT_VISIBLE",
        "POOR_POSITIONING",
        "REFLECTION_GLARE",
        "OTHER"
    ]

    if usable in [
        "NO",
        "UNSURE"
    ]:

        reason_index = (
            reason_options.index(
                current_reason
            )
            if current_reason in reason_options
            else None
        )

        unusable_reason = st.radio(
            "Why is the image unusable / uncertain?",
            reason_options,
            index=reason_index,
            horizontal=True,
            key=f"reason_{registry_id}"
        )


    # ======================================================
    # CATARACT PRESENT
    # ======================================================

    cataract_choices = [
        "YES",
        "NO",
        "UNSURE"
    ]

    cataract_index = (
        cataract_choices.index(
            current_cataract
        )
        if current_cataract in cataract_choices
        else None
    )

    cataract = st.radio(
        "Cataract present?",
        cataract_choices,
        index=cataract_index,
        horizontal=True,
        key=f"cataract_{registry_id}"
    )


    # ======================================================
    # LOCS III VALUES
    # ======================================================

    st.markdown(
        "### LOCS III values"
    )

    st.caption(
        "Enter only if the reviewer can genuinely "
        "assess the value. Otherwise leave blank."
    )


    no_value = st.text_input(
        "Nuclear Opalescence (NO)",
        value=clean_value(
            row["nuclear_opalescence_locs3"]
        ),
        key=f"no_{registry_id}"
    )


    nc_value = st.text_input(
        "Nuclear Color (NC)",
        value=clean_value(
            row["nuclear_color_locs3"]
        ),
        key=f"nc_{registry_id}"
    )


    cortical_value = st.text_input(
        "Cortical",
        value=clean_value(
            row["cortical_locs3"]
        ),
        key=f"cortical_{registry_id}"
    )


    psc_value = st.text_input(
        "Posterior Subcapsular Cataract (PSC)",
        value=clean_value(
            row["psc_locs3"]
        ),
        key=f"psc_{registry_id}"
    )


    # ======================================================
    # OVERALL SEVERITY
    # ======================================================

    severity_choices = [
        "NORMAL",
        "MILD",
        "MODERATE",
        "SEVERE",
        "UNSURE"
    ]

    severity_index = (
        severity_choices.index(
            current_severity
        )
        if current_severity in severity_choices
        else None
    )

    severity = st.radio(
        "Overall severity",
        severity_choices,
        index=severity_index,
        horizontal=True,
        key=f"severity_{registry_id}"
    )


    # ======================================================
    # REVIEWER ID
    # ======================================================

    saved_reviewer = clean_value(
        row["reviewer_id"]
    )

    reviewer_widget_key = (
        f"reviewer_{registry_id}"
    )


    # ------------------------------------------------------
    # FIRST TIME IMAGE IS OPENED
    # ------------------------------------------------------

    if reviewer_widget_key not in st.session_state:

        # Existing reviewed image
        if saved_reviewer.strip() != "":

            st.session_state[
                reviewer_widget_key
            ] = saved_reviewer

        # New image
        else:

            st.session_state[
                reviewer_widget_key
            ] = st.session_state.get(
                "default_reviewer_id",
                ""
            )


    # ------------------------------------------------------
    # REFILL EMPTY REVIEWER USING SESSION ID
    # ------------------------------------------------------

    elif (
        saved_reviewer.strip() == ""
        and str(
            st.session_state[
                reviewer_widget_key
            ]
        ).strip() == ""
    ):

        st.session_state[
            reviewer_widget_key
        ] = st.session_state.get(
            "default_reviewer_id",
            ""
        )


    reviewer_id = st.text_input(
        "Reviewer ID",
        key=reviewer_widget_key
    )


    # ======================================================
    # COMMENTS
    # ======================================================

    comments = st.text_area(
        "Comments",
        value=clean_value(
            row["comments"]
        ),
        key=f"comments_{registry_id}"
    )


# ==========================================================
# VALIDATION + SAVE
# ==========================================================

def save_current():
    """
    Validate the current record before saving.
    """

    # ------------------------------------------------------
    # REVIEWER REQUIRED
    # ------------------------------------------------------

    if reviewer_id.strip() == "":

        st.warning(
            "Please enter Reviewer ID."
        )

        return False


    # ------------------------------------------------------
    # USABILITY REQUIRED
    # ------------------------------------------------------

    if usable is None:

        st.warning(
            "Please select Clinical image usable."
        )

        return False


    # ------------------------------------------------------
    # REASON REQUIRED IF NO / UNSURE
    # ------------------------------------------------------

    if usable in [
        "NO",
        "UNSURE"
    ]:

        if unusable_reason is None:

            st.warning(
                "Please select a reason for the "
                "unusable/uncertain image."
            )

            return False


    # ------------------------------------------------------
    # CATARACT STATUS REQUIRED FOR USABLE IMAGE
    # ------------------------------------------------------

    if (
        usable == "YES"
        and cataract is None
    ):

        st.warning(
            "Please select Cataract present?"
        )

        return False


    # ------------------------------------------------------
    # SEVERITY REQUIRED IF CATARACT PRESENT
    # ------------------------------------------------------

    if (
        usable == "YES"
        and cataract == "YES"
        and severity is None
    ):

        st.warning(
            "Please select Overall severity, "
            "or choose UNSURE."
        )

        return False


    # ======================================================
    # SAVE
    # ======================================================

    df.at[
        index,
        "clinical_image_usable"
    ] = usable


    # Clear reason when image is usable
    if usable == "YES":

        df.at[
            index,
            "unusable_reason"
        ] = ""

    else:

        df.at[
            index,
            "unusable_reason"
        ] = unusable_reason or ""


    df.at[
        index,
        "cataract_present"
    ] = cataract or ""


    df.at[
        index,
        "nuclear_opalescence_locs3"
    ] = no_value.strip()


    df.at[
        index,
        "nuclear_color_locs3"
    ] = nc_value.strip()


    df.at[
        index,
        "cortical_locs3"
    ] = cortical_value.strip()


    df.at[
        index,
        "psc_locs3"
    ] = psc_value.strip()


    df.at[
        index,
        "overall_severity"
    ] = severity or ""


    df.at[
        index,
        "reviewer_id"
    ] = reviewer_id.strip()


    df.at[
        index,
        "review_date"
    ] = date.today().isoformat()


    df.at[
        index,
        "comments"
    ] = comments.strip()


    save_data(
        df
    )


    return True


# ==========================================================
# NAVIGATION
# ==========================================================

st.divider()


previous_col, save_col, next_col = st.columns(
    [1, 1, 1]
)


# ==========================================================
# PREVIOUS
# ==========================================================

with previous_col:

    if st.button(
        "⬅ Previous",
        use_container_width=True
    ):

        st.session_state.index = max(
            0,
            index - 1
        )

        st.rerun()


# ==========================================================
# SAVE
# ==========================================================

with save_col:

    if st.button(
        "💾 Save",
        use_container_width=True
    ):

        if save_current():

            st.success(
                "Saved successfully."
            )


# ==========================================================
# SAVE AND NEXT
# ==========================================================

with next_col:

    if st.button(
        "💾 Save & Next ➡",
        use_container_width=True,
        type="primary"
    ):

        if save_current():

            st.session_state.index = min(
                total_images - 1,
                index + 1
            )

            st.rerun()


# ==========================================================
# JUMP TO IMAGE
# ==========================================================

st.divider()


jump_number = st.number_input(
    "Jump to image number",
    min_value=1,
    max_value=total_images,
    value=index + 1,
    step=1
)


if st.button(
    "Go to image"
):

    st.session_state.index = (
        int(jump_number) - 1
    )

    st.rerun()


# ==========================================================
# SAFETY NOTE
# ==========================================================

st.divider()


st.info(
    "This tool records clinician/reviewer labels only. "
    "It does not automatically generate diagnoses, "
    "severity labels, LOCS III scores, or urgency decisions."
)
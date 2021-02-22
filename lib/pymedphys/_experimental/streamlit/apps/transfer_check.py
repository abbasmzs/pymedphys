# Copyright (C) 2020 Jacob Rembish

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pymedphys._imports import streamlit as st

from pymedphys._streamlit import categories
from pymedphys._streamlit.utilities.mosaiq import get_cached_mosaiq_connection

from pymedphys._experimental.chartchecks.compare import (
    colour_results,
    compare_to_mosaiq,
)
from pymedphys._experimental.chartchecks.dose_constraints import CONSTRAINTS
from pymedphys._experimental.chartchecks.dvh_helpers import calc_dvh, plot_dvh
from pymedphys._experimental.chartchecks.helpers import (
    get_all_dicom_treatment_info,
    get_all_treatment_data,
    get_staff_initials,
)
from pymedphys._experimental.chartchecks.structure_aliases import ALIASES
from pymedphys._experimental.chartchecks.tolerance_constants import (
    SITE_CONSTANTS,
    TOLERANCE_TYPES,
)

CATEGORY = categories.PRE_ALPHA
TITLE = "Pre-Treatment Data Transfer Check"


def get_patient_files():
    dicomFiles = st.file_uploader(
        "Please select a RP file.", accept_multiple_files=True
    )

    files = {}
    for dicomFile in dicomFiles:
        name = dicomFile.name
        if "RP" in name:
            files["rp"] = dicomFile
        elif "RD" in name:
            files["rd"] = dicomFile
        elif "RS" in name:
            files["rs"] = dicomFile
        elif "CT" in name:
            files["ct"] = dicomFile
        else:
            continue
    return files


def limit_mosaiq_info_to_current_versions(mosaiq_treatment_info):
    mosaiq_treatment_info = mosaiq_treatment_info[
        (mosaiq_treatment_info["site_version"] == 0)
        & (mosaiq_treatment_info["site_setup_version"] == 0)
        & (mosaiq_treatment_info["field_version"] == 0)
    ]

    mosaiq_treatment_info = mosaiq_treatment_info.reset_index(drop=True)
    return mosaiq_treatment_info


def verify_basic_patient_info(dicom_table, mosaiq_table, mrn):
    st.subheader("Patient:")
    dicom_name = (
        dicom_table.loc[0, "first_name"] + " " + dicom_table.loc[0, "last_name"]
    )
    mosaiq_name = (
        mosaiq_table.loc[0, "first_name"] + " " + mosaiq_table.loc[0, "last_name"]
    )

    if dicom_name == mosaiq_name:
        st.success("Name: " + dicom_name)
    else:
        st.error("Name: " + dicom_name)

    if mrn == mosaiq_table.loc[0, "mrn"]:
        st.success("MRN: " + mrn)
    else:
        st.error("MRN: " + mrn)

    DOB = str(mosaiq_table.loc[0, "dob"])[0:10]
    dicom_DOB = dicom_table.loc[0, "dob"]
    if DOB == dicom_DOB[0:4] + "-" + dicom_DOB[4:6] + "-" + dicom_DOB[6:8]:
        st.success("DOB: " + DOB)
    else:
        st.error("DOB: " + DOB)

    return


def check_site_approval(mosaiq_table, connection):
    st.subheader("Approval Status:")

    if mosaiq_table.loc[0, "create_id"] is not None:
        try:
            site_initials = get_staff_initials(
                connection, str(int(mosaiq_table.loc[0, "create_id"]))
            )
        except (TypeError, ValueError, AttributeError):
            site_initials = ""

    # Check site setup approval
    if all(i == 5 for i in mosaiq_table.loc[:, "site_setup_status"]):
        st.success("Site Setup Approved")
    else:
        for i in mosaiq_table.loc[:, "site_setup_status"]:
            if i != 5:
                st.error("Site Setup " + SITE_CONSTANTS[i])
                break

    # Check site approval
    if all(i == 5 for i in mosaiq_table.loc[:, "site_status"]):
        st.success("RX Approved by " + str(site_initials[0][0]))
    else:
        st.error("RX Approval Pending")

    return


def drop_irrelevant_mosaiq_fields(dicom_table, mosaiq_table):
    index = []
    for j in dicom_table.loc[:, "field_label"]:
        for i in range(len(mosaiq_table)):
            if mosaiq_table.loc[i, "field_label"] == j:
                index.append(i)

    # Create a list of indices which contain fields not within the RP file
    remove = []
    for i in mosaiq_table.iloc[:].index:
        if i not in index:
            remove.append(i)

    # Drop all indices in the remove list to get rid of fields irrelevant for this comparison
    mosaiq_table = mosaiq_table.drop(remove)
    mosaiq_table = mosaiq_table.sort_index(axis=1)
    mosaiq_table = mosaiq_table.sort_values(by=["field_label"])

    return mosaiq_table


def select_field_for_comparison(dicom_table, mosaiq_table):
    rx_selection = st.radio("Select RX: ", mosaiq_table.site.unique())
    rx_fields = mosaiq_table[mosaiq_table["site"] == rx_selection]["field_name"].values

    # create a radio selection of fields to compare, only fields within selected rx appear as choices
    field_selection = st.radio("Select field to compare:", rx_fields)
    selected_label = mosaiq_table[mosaiq_table["field_name"] == field_selection][
        "field_label"
    ]
    dicom_field_selection = dicom_table[
        dicom_table["field_label"] == selected_label.values[0]
    ]["field_name"].values[0]

    return field_selection, selected_label, dicom_field_selection


def check_for_field_approval(mosaiq_table, field_selection, connection):
    try:
        field_approval_id = mosaiq_table[mosaiq_table["field_name"] == field_selection][
            "field_approval"
        ]

        field_approval_initials = get_staff_initials(
            connection, str(int(field_approval_id.iloc[0]))
        )
        st.write("**Field Approved by: **", field_approval_initials[0][0])
    except (TypeError, ValueError, AttributeError):
        st.write("This field is not approved.")

    return


def show_fx_pattern_and_comments(mosaiq_table, field_selection):
    fx_pattern = mosaiq_table[mosaiq_table["field_name"] == field_selection][
        "fraction_pattern"
    ]
    st.write("**FX Pattern**: ", fx_pattern.iloc[0])

    # Extract and write comments from MOSAIQ for the specific field
    comments = mosaiq_table[mosaiq_table["field_name"] == field_selection]["notes"]
    st.write("**Comments**: ", comments.iloc[0])

    return


def show_field_rx(dicom_table, selected_label):
    st.write(
        "**RX**: ",
        dicom_table[dicom_table["field_label"] == selected_label.values[0]][
            "rx"
        ].values[0],
    )

    return


def show_comparison_of_selected_fields(dicom_field_selection, results):
    dicom_field = str(dicom_field_selection) + "_DICOM"
    mosaiq_field = str(dicom_field_selection) + "_MOSAIQ"
    display_results = results[[dicom_field, mosaiq_field]]

    display_results = display_results.drop(
        ["dob", "first_name", "last_name", "mrn"], axis=0
    )

    display_results = display_results.style.apply(colour_results, axis=1)
    st.dataframe(display_results.set_precision(2), height=1000)

    return


def compare_structure_with_constraints(roi, structure, dvh_calcs, constraints):
    structure_constraints = constraints[structure]
    structure_dvh = dvh_calcs[roi]
    for type, constraint in structure_constraints.items():
        if type == "Mean" and constraint is not " ":
            for val in range(0, len(constraint)):
                st.write(structure, " Mean: ", structure_dvh.mean)

        elif type == "Max" and constraint is not " ":
            for val in range(0, len(constraint)):
                st.write(structure, " Max: ", structure_dvh.max)

        elif type == "V%" and constraint is not " ":
            for val in range(0, len(constraint)):
                st.write(
                    structure,
                    " V%: ",
                    structure_dvh.dose_constraint(constraint[val][1] * 100),
                )
    return


def main():
    server = "PRDMOSAIQIWVV01.utmsa.local"
    connection = get_cached_mosaiq_connection(server)

    st.sidebar.header("Instructions:")
    st.sidebar.markdown(
        """
    To use this application, you must have the RP file of the plan you want to check. This can be exported in Pinnacle.
    You will get an error if you select a QA RP file.

    When exporting the DICOM, only the RP is needed. Once you have that, you can select it where prompted and the application
    will run.
    """
    )

    files = get_patient_files()

    if "rp" in files:

        try:
            dicom_table = get_all_dicom_treatment_info(files["rp"])
            dicom_table = dicom_table.sort_values(["field_label"])
        except AttributeError:
            st.write("Please select a new RP file.")
            st.stop()

        mrn = dicom_table.loc[0, "mrn"]
        mosaiq_table = get_all_treatment_data(connection, mrn)
        mosaiq_table = drop_irrelevant_mosaiq_fields(dicom_table, mosaiq_table)
        mosaiq_table = limit_mosaiq_info_to_current_versions(mosaiq_table)

        verify_basic_patient_info(dicom_table, mosaiq_table, mrn)
        check_site_approval(mosaiq_table, connection)

        results = compare_to_mosaiq(dicom_table, mosaiq_table)
        results = results.transpose()

        (
            field_selection,
            selected_label,
            dicom_field_selection,
        ) = select_field_for_comparison(dicom_table, mosaiq_table)
        st.subheader("Comparison")
        if len(selected_label) != 0:
            show_field_rx(dicom_table, selected_label)
            check_for_field_approval(mosaiq_table, field_selection, connection)
            show_comparison_of_selected_fields(dicom_field_selection, results)
            show_fx_pattern_and_comments(mosaiq_table, field_selection)

        # Create a checkbox to allow users to view all DICOM plan information
        show_dicom = st.checkbox("View complete DICOM table.")
        if show_dicom:
            st.subheader("DICOM Table")
            st.dataframe(dicom_table, height=1000)

        # Create a checkbox to allow users to view all MOSAIQ information
        show_mosaiq = st.checkbox("View complete Mosaiq table.")
        if show_mosaiq:
            st.subheader("Mosaiq Table")
            st.dataframe(mosaiq_table, height=1000)

        if "rs" in files and "rd" in files:

            show_dvh = st.checkbox("Create DVH Plot")
            if show_dvh:
                dvh_calcs = calc_dvh(files["rs"], files["rd"])
                plot_dvh(dvh_calcs)

                rois = dvh_calcs.keys()
                for roi in rois:
                    for structure, aliases in ALIASES.items():
                        if roi.lower() in aliases:
                            compare_structure_with_constraints(
                                roi, structure, dvh_calcs, constraints=CONSTRAINTS
                            )

            dvh_lookup = st.checkbox("DVH Lookup Table")
            if dvh_lookup:
                default = [
                    "< Select an ROI >",
                ]
                roi_list = list(dvh_calcs.keys())
                roi_list = default + roi_list
                roi_select = st.selectbox("Select an ROI: ", roi_list)

                if roi_select != "< Select an ROI >":
                    selected_structure = dvh_calcs[roi_select]
                    volume = st.number_input("Input relative volume: ")
                    st.write(selected_structure.dose_constraint(volume))

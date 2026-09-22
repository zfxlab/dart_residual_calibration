"""Keep explicitly keyed editable widgets alive across in-session navigation."""

import streamlit as st


def retain_page_state(page):
    # Streamlit deletes widget-owned keys when their page is not rendered.
    # Reassign only editable state, never button/upload/chart event state.
    keys = {"project_name", "model_distance", "model_yaw", "selected_sample"}
    prefixes = ("probe_", "calibration_view_")
    for key in list(st.session_state):
        inactive_calibration = page != "calibration" and (key in keys or key.startswith(prefixes))
        inactive_observation = page != "observation" and key.startswith("observation_")
        if inactive_calibration or inactive_observation:
            st.session_state[key] = st.session_state[key]
    previous = st.session_state.get("active_tool_page")
    st.session_state.active_tool_page = page
    return previous != page

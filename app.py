"""AI Sales Qualification Agent - Streamlit Application.

Interactive sales qualification interface with configurable rules,
local deterministic pricing tool simulation, Gemini API analysis,
and strict Pydantic structured output validation.
"""

import json
import os
import streamlit as st
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

from core.schemas import SalesLeadQualification, ToolResult
from core.config import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_CONVERSATION_STYLE,
    DEFAULT_QUALIFICATION_CRITERIA,
    DEFAULT_FOLLOW_UP_RULES,
    TEST_CASES,
)
from core.tools import calculate_price_estimate, extract_lead_heuristics
from core.agent import SalesAgent

# Page configuration
st.set_page_config(
    page_title="AI Sales Qualification Agent",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for polished assessment interface
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
        color: #1E293B;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .badge-qualified {
        background-color: #DCFCE7;
        color: #166534;
        padding: 0.35rem 0.8rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.95rem;
        display: inline-block;
        border: 1px solid #86EFAC;
    }
    .badge-unqualified {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 0.35rem 0.8rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.95rem;
        display: inline-block;
        border: 1px solid #FCA5A5;
    }
    .badge-needs-info {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 0.35rem 0.8rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.95rem;
        display: inline-block;
        border: 1px solid #FDE68A;
    }
    .tool-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 1rem;
        margin-top: 0.5rem;
        margin-bottom: 1rem;
    }
    .card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Resolve API Key securely (Env var -> Streamlit secrets -> None)
def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key and hasattr(st, "secrets"):
        try:
            if "GEMINI_API_KEY" in st.secrets:
                key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            pass
    return key


def get_model_name() -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    if hasattr(st, "secrets"):
        try:
            if "GEMINI_MODEL" in st.secrets:
                model = st.secrets["GEMINI_MODEL"]
        except Exception:
            pass
    return model


# Initialize Session State
if "customer_input" not in st.session_state:
    st.session_state.customer_input = ""
if "simulate_failure" not in st.session_state:
    st.session_state.simulate_failure = False
if "history" not in st.session_state:
    st.session_state.history = []
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "pre_tool_result" not in st.session_state:
    st.session_state.pre_tool_result = None

# ==========================================
# SIDEBAR: Configurable Prompts & Rules
# ==========================================
with st.sidebar:
    st.header("⚙️ Configuration & Prompts")
    st.caption("All business rules and agent instructions below are fully editable.")

    # API Configuration
    st.subheader("🔑 Gemini API Settings")
    default_key = get_api_key()
    api_key_input = st.text_input(
        "Gemini API Key",
        value=default_key,
        type="password",
        help="Reads automatically from GEMINI_API_KEY env var or Streamlit secrets. Enter manually if needed.",
    )
    effective_api_key = api_key_input.strip() or default_key

    env_model = get_model_name()
    model_options = ["gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    if env_model not in model_options:
        model_options.insert(0, env_model)
    selected_index = model_options.index(env_model)

    selected_model = st.selectbox(
        "Gemini Model",
        options=model_options,
        index=selected_index,
        help="Configurable via GEMINI_MODEL env var or dropdown.",
    )

    if effective_api_key:
        st.success("API Key detected and active", icon="✅")
    else:
        st.warning("No API key detected. Set GEMINI_API_KEY or enter above.", icon="⚠️")

    st.divider()

    # Tool Simulation Checkbox (Mandatory Requirement)
    st.subheader("🛠️ Tool Simulation Controls")
    simulate_failure = st.checkbox(
        "Simulate tool failure",
        value=st.session_state.simulate_failure,
        help="When enabled, calculate_price_estimate returns a real structured error. The agent must not invent pricing.",
    )
    st.session_state.simulate_failure = simulate_failure

    st.divider()

    # Configurable Prompts and Rules
    st.subheader("📝 Configurable Prompts & Rules")

    system_prompt = st.text_area(
        "System Prompt / Agent Role",
        value=DEFAULT_SYSTEM_PROMPT,
        height=220,
        help="Core role, truthfulness rules, anti-injection directives.",
    )

    conversation_style = st.text_area(
        "Conversation Style",
        value=DEFAULT_CONVERSATION_STYLE,
        height=80,
        help="Tone and demeanor for interacting with enterprise customers.",
    )

    qualification_criteria = st.text_area(
        "Qualification Criteria (Business Rules)",
        value=DEFAULT_QUALIFICATION_CRITERIA,
        height=180,
        help="Configurable thresholds for Qualified, Unqualified, and Needs More Information.",
    )

    follow_up_rules = st.text_area(
        "Rules for Follow-up Questions",
        value=DEFAULT_FOLLOW_UP_RULES,
        height=160,
        help="Logic dictating which questions the agent asks when details are missing or conflicting.",
    )


# ==========================================
# MAIN INTERFACE
# ==========================================
st.markdown('<div class="main-title">AI Sales Qualification Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Automated B2B Lead Qualification, Deterministic Pricing Calculation, and Structured Extraction</div>',
    unsafe_allow_html=True,
)

# Test Cases Section
with st.expander("🧪 Assessment Test Cases (Click any button to auto-fill input)", expanded=True):
    st.markdown("Select any pre-configured assessment test case below to populate the customer message:")
    cols = st.columns(len(TEST_CASES))
    for idx, (name, test_data) in enumerate(TEST_CASES.items()):
        with cols[idx]:
            if st.button(name, key=f"btn_tc_{idx}", use_container_width=True):
                st.session_state.customer_input = test_data["text"]
                st.session_state.simulate_failure = test_data["simulate_failure"]
                st.rerun()

# Customer Message Input Area
st.subheader("1. Customer Conversation")
customer_text = st.text_area(
    "Customer Message / Inquiry:",
    value=st.session_state.customer_input,
    height=140,
    placeholder="Describe your project, required seats, budget, and implementation timeline here...",
)
st.session_state.customer_input = customer_text

col_btn1, col_btn2, _ = st.columns([1.5, 1.2, 5])
with col_btn1:
    analyze_clicked = st.button("🚀 Analyze Lead", type="primary", use_container_width=True)
with col_btn2:
    if st.button("🔄 Clear", use_container_width=True):
        st.session_state.customer_input = ""
        st.session_state.analysis_result = None
        st.session_state.pre_tool_result = None
        st.rerun()

# Execution Logic
if analyze_clicked:
    if not customer_text.strip():
        st.warning("Please enter a customer message or pick a test case above.")
    elif not effective_api_key:
        st.error(
            "Gemini API Key is missing! Please provide it in the sidebar or set the `GEMINI_API_KEY` environment variable.",
            icon="🚨",
        )
    else:
        agent = SalesAgent(api_key=effective_api_key, model_name=selected_model)

        with st.spinner("Executing local price calculation tool and analyzing lead with Gemini..."):
            lead_result, tool_result, err = agent.analyze_lead(
                customer_message=customer_text,
                simulate_failure=st.session_state.simulate_failure,
                system_prompt=system_prompt,
                conversation_style=conversation_style,
                qualification_criteria=qualification_criteria,
                follow_up_rules=follow_up_rules,
            )

            st.session_state.pre_tool_result = tool_result

            if err:
                st.error(err)
                st.session_state.analysis_result = None
            else:
                st.session_state.analysis_result = lead_result
                # Save to history
                st.session_state.history.append({
                    "input": customer_text,
                    "status": lead_result.lead_status,
                    "reason": lead_result.classification_reason,
                    "tool": tool_result.model_dump(),
                })


# ==========================================
# OUTPUT SECTIONS
# ==========================================
if st.session_state.analysis_result:
    result: SalesLeadQualification = st.session_state.analysis_result
    tool_res: ToolResult = st.session_state.pre_tool_result or result.tool_result

    st.divider()
    st.subheader("2. Lead Qualification Results")

    # Section 1: Lead Decision
    col_status, col_intent = st.columns([1.5, 2.5])
    with col_status:
        st.markdown("**Lead Qualification Status:**")
        if result.lead_status == "Qualified":
            st.markdown('<div class="badge-qualified">🟢 Qualified</div>', unsafe_allow_html=True)
        elif result.lead_status == "Unqualified":
            st.markdown('<div class="badge-unqualified">🔴 Unqualified</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="badge-needs-info">🟡 Needs More Information</div>', unsafe_allow_html=True)

    with col_intent:
        st.markdown("**Evaluated Customer Intent:**")
        st.info(result.customer_intent or "Intent not specified")

    # Section 2: Explanation
    st.markdown("### 📋 Explanation")
    st.write(result.classification_reason or "No explanation provided.")

    # Extracted Details Overview Grid
    st.markdown("#### Extracted Customer Information")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Customer Name", result.customer_name or "null")
    with c2:
        st.metric("Contact Details", result.contact_details or "null")
    with c3:
        st.metric("Stated Budget", result.budget or "null")
    with c4:
        st.metric("Timeline", result.timeline or "null")

    if result.requirements:
        st.markdown(f"**Identified Requirements:** {result.requirements}")

    # Safety or Boundary Alert
    if result.safety_note:
        st.warning(f"🛡️ **Safety & Security Note:** {result.safety_note}", icon="⚠️")

    # Section 3: Missing Information & Follow-up Questions
    col_missing, col_followup = st.columns(2)
    with col_missing:
        st.markdown("### ❓ Missing Information")
        if result.missing_information:
            for item in result.missing_information:
                st.markdown(f"- ⚠️ **{item}**")
        else:
            st.success("All essential qualification information has been provided.")

    with col_followup:
        st.markdown("### 💬 Recommended Follow-up Questions")
        if result.follow_up_questions:
            for q in result.follow_up_questions:
                st.markdown(f"- ❓ *\"{q}\"*")
        else:
            st.write("No follow-up questions needed.")

    # Section 4: Tool / Function Result
    st.markdown("### 🧮 Tool Result: `calculate_price_estimate`")
    if tool_res.status == "success":
        st.markdown(
            f"""
            <div class="tool-box">
                <b>Status:</b> <span style="color:green; font-weight:600;">SUCCESS</span> &nbsp;|&nbsp;
                <b>Tool:</b> <code>{tool_res.tool_name}</code> &nbsp;|&nbsp;
                <b>Plan:</b> <b>{tool_res.plan}</b><br/>
                <b>Estimated Price:</b> <span style="font-size:1.25rem; font-weight:700; color:#166534;">₹{tool_res.estimated_price_inr:,} INR</span><br/>
                <b>Calculation Details:</b> {tool_res.message}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="tool-box" style="border-left: 4px solid #EF4444; background-color:#FEF2F2;">
                <b>Status:</b> <span style="color:#DC2626; font-weight:600;">ERROR (Simulated or Service Failure)</span> &nbsp;|&nbsp;
                <b>Tool:</b> <code>{tool_res.tool_name}</code><br/>
                <b>Error Message:</b> {tool_res.message}<br/>
                <i>Note: The agent strictly complies with safety policy and does not fabricate estimates when the tool fails.</i>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Section 5: Structured JSON Output
    st.markdown("### 📦 Structured JSON Output (Pydantic Validated)")
    st.caption("Validated against exact assessment schema:")
    st.json(result.model_dump())

# Conversation / Analysis History
if st.session_state.history:
    with st.expander(f"📜 Session History ({len(st.session_state.history)} analyzed leads)"):
        for i, item in enumerate(reversed(st.session_state.history)):
            st.markdown(f"**Lead #{len(st.session_state.history) - i}** - Status: `{item['status']}`")
            st.markdown(f"> *\"{item['input']}\"*")
            st.caption(f"Reason: {item['reason']}")
            st.divider()

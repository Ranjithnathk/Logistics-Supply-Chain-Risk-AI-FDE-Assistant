import os
import sys
import uuid
import json
import urllib
import re
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from langchain_core.messages import HumanMessage, ToolMessage

# ==========================================
# 1. IMMEDIATE PATH & ENVIRONMENT RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent  # points to src/
project_root = script_dir.parent              # climbs to project root

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env")

# Import the compiled graph and tools list dynamically
from src.orchestrator import fde_agent, llm

# ==========================================
# 2. SQL CREDENTIALS MAPPING FROM .ENV
# ==========================================
db_host = os.getenv("SQL_SERVER_HOST", "localhost")
db_port = os.getenv("SQL_SERVER_PORT", "1433")
db_user = os.getenv("SQL_AGENT_USER", "USR_FDE_RO")
db_password = os.getenv("SQL_AGENT_PASSWORD")

# Engine for the Agent to write logs using its standard credentials
connection_string = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={db_host},{db_port};"
    f"DATABASE=master;"
    f"UID={db_user};"
    f"PWD={db_password};"
    f"Encrypt=no;"
    f"TrustServerCertificate=yes;"
)

log_params = urllib.parse.quote_plus(connection_string)
log_engine = create_engine(f"mssql+pyodbc:///?odbc_connect={log_params}")

def write_audit_log(session_id, node_name, tool_name, content):
    """Silently writes agent execution traces to the SQL audit table using agent permissions."""
    try:
        with log_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO FDE_VIEWS.AgentAuditLog (SessionID, NodeExecuted, ToolName, Content)
                VALUES (:session_id, :node_name, :tool_name, :content)
            """), {
                "session_id": session_id,
                "node_name": node_name,
                "tool_name": tool_name,
                "content": content
            })
            conn.commit()
    except Exception as e:
        print(f"Audit Log Failed (Silent): {e}")

def generate_followup_questions(user_question: str, agent_response: str) -> list[str]:
    """Generates 3 short follow-up questions based on the last Q&A exchange."""
    prompt = f"""Based on this dispatcher Q&A exchange, suggest exactly 3 short, specific follow-up questions
a logistics dispatcher might naturally ask next. Keep each under 12 words.
Return ONLY a valid JSON array of 3 strings — no markdown, no explanation, no code fences.

User asked: {user_question}
Agent answered: {agent_response[:800]}

Example output format: ["question one?", "question two?", "question three?"]
"""
    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()
        # Strip markdown code fences if the model added them anyway
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        questions = json.loads(raw)
        if isinstance(questions, list) and len(questions) >= 3:
            return [str(q) for q in questions[:3]]
    except Exception as e:
        print(f"Follow-up generation failed (silent): {e}")
    return []

# ==========================================
# 3. PAGE CONFIGURATION & ENTERPRISE THEME
# ==========================================
st.set_page_config(
    page_title="Logistics & Supply Chain Risk Assistant | AI FDE",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* ---------- Base app ---------- */
    .stApp { background-color: #FFFFFF; color: #0F172A; }
    #MainMenu, footer, header { visibility: hidden; }

    /* ---------- Sidebar ---------- */
    div[data-testid="stSidebar"] {
        background-color: #F1F5F9;
        border-right: 1px solid #E2E8F0;
    }
    div[data-testid="stSidebar"] * { color: #0F172A !important; }

    /* ---------- Headings ---------- */
    h1, h2, h3, h4, h5 { color: #0F172A !important; }

    /* ---------- Code blocks & inline code ---------- */
    .stMarkdown code { background-color: #E2E8F0 !important; color: #2563EB !important; }
    pre, .stCodeBlock, div[data-testid="stCodeBlock"] {
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px;
    }

    /* ---------- Text & password inputs ---------- */
    .stTextInput input {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px;
    }
    .stTextInput input:focus {
        border: 1px solid #2563EB !important;
        box-shadow: 0 0 0 1px #2563EB !important;
    }
    .stTextInput label, .stRadio label, .stForm label { color: #334155 !important; }

    /* ---------- Buttons ---------- */
    .stButton button {
        background-color: #F1F5F9;
        color: #2563EB;
        border: 1px solid #CBD5E1;
        border-radius: 8px;
        transition: all 0.2s ease;
    }
    .stButton button:hover {
        background-color: #2563EB;
        color: #FFFFFF;
        border: 1px solid #2563EB;
    }
    .stFormSubmitButton button {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        font-weight: 600;
        border: none !important;
    }
    .stFormSubmitButton button:hover { background-color: #1D4ED8 !important; }

    /* ---------- Expanders ---------- */
    .streamlit-expanderHeader, div[data-testid="stExpander"] summary {
        background-color: #F8FAFC !important;
        color: #2563EB !important;
        border-radius: 6px;
        border: 1px solid #E2E8F0 !important;
    }

    /* ---------- Chat input & chat bubbles ---------- */
    .stChatInput textarea {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #CBD5E1 !important;
    }
    .stChatMessage {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }

    /* ---------- Status widget ---------- */
    div[data-testid="stStatusWidget"] {
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px;
    }

    /* ---------- Dataframe (audit log) ---------- */
    .stDataFrame, div[data-testid="stDataFrame"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px;
    }

    /* ---------- Radio buttons (sidebar mode switch) ---------- */
    div[role="radiogroup"] label {
        background-color: #FFFFFF;
        padding: 8px 12px;
        border-radius: 8px;
        margin-bottom: 4px;
        border: 1px solid #E2E8F0;
    }

    /* ---------- Badges ---------- */
    .status-badge {
        display:inline-block; background-color:#DCFCE7; color:#15803D;
        padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600;
    }

    /* ---------- Example / follow-up prompt buttons ---------- */
    .example-btn button {
        text-align: left !important;
        white-space: normal !important;
        height: auto !important;
        padding: 10px 14px !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. MULTI-USER STATE & THREAD MANAGEMENT
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = []

if "pending_input" not in st.session_state:
    st.session_state.pending_input = None

thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}

# ==========================================
# 5. SIDEBAR NAVIGATION & METADATA
# ==========================================
with st.sidebar:
    logo_path = script_dir / "image_L25X5q.png"
    #st.markdown("<h1 style='font-size:48px; margin-bottom:0;'>🚛</h1>", unsafe_allow_html=True)
    st.title("Command Center")
    #st.caption("Legacy MSSQL · RAG · LangGraph Agents")

    app_mode = st.radio("System Mode", ["🧊 Dispatch Console", "🛡️ Security & Audit Logs"])

    st.markdown("---")
    st.markdown(f"**Reasoning Architecture:** `{os.getenv('Agent_llm', 'OPENAI')}`")
    #st.markdown(f"**Embeddings:** `{os.getenv('Embeddings_model', 'LOCAL')}`")

    st.markdown("---")
    if st.button("🗑️ Purge Dispatch Workspace Session", use_container_width=True):
        st.session_state.ui_messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

# ==========================================
# 6. VIEW ROUTING (DISPATCH VS AUDIT)
# ==========================================

if app_mode == "🧊 Dispatch Console":
    # ------------------------------------------
    # TAB 1: CHAT UI & AGENT EXECUTION
    # ------------------------------------------
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.title("🚛 Logistics & Supply Chain Risk Assistant")
        st.caption("AI FDE Platform - Real-Time Decision Optimization")
    with header_col2:
        st.markdown(
            f"<div style='text-align:right; padding-top:28px;'>"
            f"<span class='status-badge'>● {os.getenv('Agent_llm', 'OPENAI')} ONLINE</span></div>",
            unsafe_allow_html=True
        )

    st.markdown("---")

    # Starter prompts shown only on a fresh session (no messages yet)
    if not st.session_state.ui_messages:
        st.markdown("##### 💡 Try asking")
        example_prompts = [
            "📍 Show me shipments with the highest route risk right now",
            "🌡️ What's the compliance threshold for fresh perishable temperature?",
            "🌦️ Check live corridor conditions near Los Angeles (33.77, -118.19)"
        ]
        ex_cols = st.columns(3)
        for col, prompt in zip(ex_cols, example_prompts):
            with col:
                st.markdown('<div class="example-btn">', unsafe_allow_html=True)
                if st.button(prompt, use_container_width=True, key=f"ex_{prompt[:12]}"):
                    st.session_state.pending_input = prompt
                st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

    # Render prior conversation history
    for idx, entry in enumerate(st.session_state.ui_messages):
        is_last_assistant_msg = (
            entry["role"] == "assistant" and idx == len(st.session_state.ui_messages) - 1
        )
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else "🤖"):
            if "traces" in entry:
                for trace in entry["traces"]:
                    if trace["type"] == "tool_input":
                        st.markdown(f"**⚡ Intent Recognized:** `{trace['name']}`")
                        with st.expander(f"📥 View Generated Input ({trace['name']})", expanded=False):
                            st.json(trace["args"])
                    elif trace["type"] == "tool_output":
                        with st.expander(f"📤 View Raw Output ({trace['name']})", expanded=False):
                            st.code(trace["content"], language="text")
            st.markdown(entry["content"])

            # Follow-up suggestions — only shown under the most recent assistant reply
            if is_last_assistant_msg and entry.get("followups"):
                st.markdown("**💬 Related questions:**")
                fu_cols = st.columns(len(entry["followups"]))
                for fu_col, fu_question in zip(fu_cols, entry["followups"]):
                    with fu_col:
                        st.markdown('<div class="example-btn">', unsafe_allow_html=True)
                        if st.button(fu_question, use_container_width=True, key=f"followup_{idx}_{fu_question[:20]}"):
                            st.session_state.pending_input = fu_question
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

    # Accept either a typed message or a clicked example/follow-up prompt
    typed_input = st.chat_input("Query fleet telemetry, corridor updates, or compliance thresholds...")
    user_input = typed_input or st.session_state.pending_input
    st.session_state.pending_input = None  # clear after consuming

    if user_input:
        st.session_state.ui_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            final_response = ""
            current_traces = []

            with st.status("🧠 Initializing Core Reasoner Node...", expanded=True) as status:
                events = fde_agent.stream(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=thread_config,
                    stream_mode="updates"
                )

                for event in events:
                    for node_name, node_state in event.items():

                        if node_name == "reasoner":
                            latest_msg = node_state["messages"][-1]

                            # A. Intercept Tool Call Requests (Inputs)
                            if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                                status.update(label="🧠 Agent generated tool parameters...")
                                for tool_call in latest_msg.tool_calls:
                                    st.markdown(f"**⚡ Intent Recognized:** `{tool_call['name']}`")
                                    with st.expander(f"📥 View Generated Input ({tool_call['name']})", expanded=False):
                                        st.json(tool_call['args'])

                                    current_traces.append({
                                        "type": "tool_input",
                                        "name": tool_call['name'],
                                        "args": tool_call['args']
                                    })

                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="reasoner",
                                        tool_name=tool_call['name'],
                                        content=json.dumps(tool_call['args'])
                                    )

                            # B. Intercept Final Generation
                            if latest_msg.content:
                                final_response = latest_msg.content
                                status.update(label="📝 Generating Operational Resolution Report...")

                                write_audit_log(
                                    session_id=st.session_state.thread_id,
                                    node_name="reasoner_final",
                                    tool_name="LLM Text Synthesis",
                                    content=final_response
                                )

                        elif node_name == "tools":
                            status.update(label="🔧 Executing Enterprise Subsystem Tools...")
                            for msg in node_state.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    with st.expander(f"📤 View Raw Output ({msg.name})", expanded=False):
                                        st.code(msg.content, language="text")

                                    current_traces.append({
                                        "type": "tool_output",
                                        "name": msg.name,
                                        "content": msg.content
                                    })

                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="tools",
                                        tool_name=msg.name,
                                        content=msg.content
                                    )

                status.update(label="Incident Matrix Evaluation Complete", state="complete", expanded=False)

            # Generate follow-up questions AFTER the status block closes, before rendering
            followup_questions = []
            if final_response:
                with st.spinner("💬 Generating related questions..."):
                    followup_questions = generate_followup_questions(user_input, final_response)

            if final_response:
                st.markdown(final_response)

                if followup_questions:
                    st.markdown("**💬 Related questions:**")
                    fu_cols = st.columns(len(followup_questions))
                    for fu_col, fu_question in zip(fu_cols, followup_questions):
                        with fu_col:
                            st.markdown('<div class="example-btn">', unsafe_allow_html=True)
                            if st.button(fu_question, use_container_width=True, key=f"followup_new_{fu_question[:20]}"):
                                st.session_state.pending_input = fu_question
                            st.markdown('</div>', unsafe_allow_html=True)

                st.session_state.ui_messages.append({
                    "role": "assistant",
                    "content": final_response,
                    "traces": current_traces,
                    "followups": followup_questions
                })
            else:
                error_fallback = "⚠️ Execution Timeout: System engine encountered an unresolved processing edge case."
                st.error(error_fallback)

        # Rerun so example/follow-up prompt clicks render through the normal chat history path
        if not typed_input:
            st.rerun()


elif app_mode == "🛡️ Security & Audit Logs":
    # ------------------------------------------
    # TAB 2: AUDIT LOG VIEWER (REQUIRES ADMIN CREDENTIALS FROM .ENV OR INPUT)
    # ------------------------------------------
    st.title("🛡️ Enterprise Agent Audit Trail")
    st.caption("Secure database inspection of FDE_VIEWS.AgentAuditLog")

    st.markdown("### Database Authorization Gate")
    st.markdown("Enter high-privilege administrative credentials (defined in `.env` as `SQL_ADMIN_USER`) to query audit logs.")

    with st.form("admin_auth_form"):
        col1, col2 = st.columns(2)
        with col1:
            input_user = st.text_input("Admin Username", value=os.getenv("SQL_ADMIN_USER", ""))
        with col2:
            input_pass = st.text_input("Admin Password", type="password", value="")

        submit_admin = st.form_submit_button("Authenticate & Load Logs", use_container_width=True)

    if submit_admin:
        expected_admin_user = os.getenv("SQL_ADMIN_USER")
        expected_admin_pass = os.getenv("SQL_ADMIN_PASSWORD")

        if input_user == expected_admin_user and input_pass == expected_admin_pass:
            try:
                # Build an isolated admin connection string for viewing data
                admin_params = urllib.parse.quote_plus(
                    "DRIVER={ODBC Driver 18 for SQL Server};"
                    f"SERVER={db_host},{db_port};"
                    "DATABASE=master;"
                    f"UID={input_user};"
                    f"PWD={input_pass};"
                    "Encrypt=no;"
                    "TrustServerCertificate=yes;"
                )
                admin_engine = create_engine(f"mssql+pyodbc:///?odbc_connect={admin_params}")

                with admin_engine.connect() as conn:
                    query = """
                        SELECT LogID, Timestamp, SessionID, NodeExecuted, ToolName, Content
                        FROM FDE_VIEWS.AgentAuditLog
                        ORDER BY Timestamp DESC
                    """
                    df = pd.read_sql(query, conn)

                st.success("✅ Authenticated successfully as Admin.")

                if not df.empty:
                    st.dataframe(
                        df,
                        column_config={
                            "LogID": st.column_config.NumberColumn("ID", format="%d"),
                            "Timestamp": st.column_config.DatetimeColumn("Execution Time", format="DD/MM/YYYY-h:mm a"),
                            "SessionID": "Session Token",
                            "NodeExecuted": "Graph Node",
                            "ToolName": "Tool Triggered",
                            "Content": "Raw Payload Data"
                        },
                        hide_index=True,
                        use_container_width=True,
                        height=600
                    )
                else:
                    st.info("No audit logs found in the database. Run a query in the Dispatch Console first.")

            except Exception as e:
                st.error(f"Database Query Failed: {e}")
        else:
            st.error("❌ Invalid Administrator Credentials.")
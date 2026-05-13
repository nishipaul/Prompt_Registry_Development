"""
Prompt Lab — Streamlit UI for prompt management + LLM testing.
Run: streamlit run prompt_lab.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE = os.getenv("PROMPT_API_BASE", "http://localhost:8000/api/v1/prompts")
LLM_GATEWAY_URL = "https://api-be.dev.simpplr.xyz/v1/chat/completions"
EXCEL_PATH = Path(__file__).parent / "llm_test_results.xlsx"
ENVIRONMENTS = ["development", "test", "uat", "production"]

st.set_page_config(page_title="Prompt Lab", page_icon="🧪", layout="wide")

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api(method: str, path: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(method, url, json=payload, timeout=15)
        return {"ok": resp.status_code < 400, "status": resp.status_code, "data": resp.json()}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": 0, "data": {"detail": f"Cannot connect to {API_BASE}. Is the server running?"}}
    except Exception as exc:
        return {"ok": False, "status": 0, "data": {"detail": str(exc)}}


api_health   = lambda: _api("GET",  "/health")
api_validate = lambda p: _api("POST", "/validate", p)
api_commit   = lambda p: _api("POST", "/commit",   p)
api_save     = lambda p: _api("POST", "/save",     p)
api_read     = lambda p: _api("POST", "/read",     p)
api_search   = lambda p: _api("POST", "/search",   p)
api_update   = lambda p: _api("POST", "/update",   p)
api_delete   = lambda p: _api("POST", "/delete",   p)
api_versions = lambda p: _api("POST", "/versions", p)

# ---------------------------------------------------------------------------
# LLM gateway
# ---------------------------------------------------------------------------

def call_llm(
    messages: List[Dict[str, str]],
    tenant_id: str,
    tenant_feature: str,
    model: str = "auto-route",
    max_tokens: int = 500,
) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "x-smtip-tid": tenant_id,
        "x-smtip-feature": tenant_feature,
    }
    payload = {
        "model": model,
        "messages": messages,
    }
    t0 = time.time()
    try:
        resp = requests.post(LLM_GATEWAY_URL, headers=headers, json=payload, timeout=60)
        latency_ms = int((time.time() - t0) * 1000)
        resp.raise_for_status()
        data = resp.json()
        return {
            "ok": True,
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "ok": False,
            "content": None,
            "error": str(exc),
            "latency_ms": int((time.time() - t0) * 1000),
        }

# ---------------------------------------------------------------------------
# Excel logger
# ---------------------------------------------------------------------------

EXCEL_COLS = [
    "run_id", "timestamp", "tenant_id", "tenant_feature",
    "prompt_handle", "environment", "version", "sub_agent",
    "prompt_text_sent", "user_context",
    "llm_response", "model_used",
    "prompt_tokens", "completion_tokens", "latency_ms",
    "status", "notes",
]


def load_results() -> pd.DataFrame:
    if EXCEL_PATH.exists():
        try:
            return pd.read_excel(EXCEL_PATH, dtype=str)
        except Exception:
            pass
    return pd.DataFrame(columns=EXCEL_COLS)


def log_result(row: Dict[str, Any]) -> None:
    df = load_results()
    new_row = pd.DataFrame([{c: str(row.get(c, "")) for c in EXCEL_COLS}])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel(EXCEL_PATH, index=False)

# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------

def show_api_result(result: Dict, success_msg: str = "Done") -> None:
    if result["ok"]:
        st.success(success_msg)
        st.json(result["data"])
    else:
        st.error(f"HTTP {result['status']}")
        st.json(result["data"])


def metadata_inputs(key: str) -> Dict[str, Any]:
    """Render metadata sub-form. key is a unique prefix to avoid widget ID clashes."""
    c1, c2 = st.columns(2)
    with c1:
        tid   = st.text_input("Tenant ID *",       key=f"{key}_tid")
        tf    = st.text_input("Tenant Feature *",  key=f"{key}_tf")
        mn    = st.text_input("Model Name *",      key=f"{key}_mn")
        mp    = st.text_input("Model Provider *",  key=f"{key}_mp")
    with c2:
        an    = st.text_input("Agent Name *",      key=f"{key}_an")
        fw    = st.text_input("Framework",         key=f"{key}_fw")
        lb    = st.text_input("Labels (comma-sep) *", key=f"{key}_lb")
        am    = st.text_area("Additional Metadata (JSON)", "{}", height=68, key=f"{key}_am")
    try:
        add_meta = json.loads(am)
    except json.JSONDecodeError:
        add_meta = {}
    return {
        "tenant_id": tid, "tenant_feature": tf,
        "model_name": mn, "model_provider": mp,
        "agent_name": an, "framework": fw or None,
        "label": [l.strip() for l in lb.split(",") if l.strip()],
        "additional_metadata": add_meta,
    }


def extract_prompt_text(prompt_data: Dict[str, Any]) -> tuple[str, str]:
    """Return (extracted_text, key_used). Falls back to JSON dump."""
    for k in ("content", "system_prompt", "prompt", "text", "message", "user_template"):
        if isinstance(prompt_data.get(k), str):
            return prompt_data[k], k
    return json.dumps(prompt_data, indent=2), "__json__"


def _parse_json(raw: str, label: str) -> Optional[Dict]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        st.error(f"JSON error in {label}: {exc}")
        return None

# ---------------------------------------------------------------------------
# Tab 1 — Prompt Management
# ---------------------------------------------------------------------------

def render_prompt_management() -> None:
    st.header("Prompt Management")

    health = api_health()
    if health["ok"]:
        st.success(f"API online — {API_BASE}")
    else:
        st.error(health["data"].get("detail", "Server unreachable"))
        st.stop()

    op = st.selectbox(
        "Select operation",
        ["Commit", "Save (Temp)", "Read", "Search", "Versions", "Update", "Delete", "Validate"],
    )
    st.divider()

    # ── COMMIT ──────────────────────────────────────────────────────────────
    if op == "Commit":
        st.subheader("Commit — Permanent Storage")
        with st.form("form_commit"):
            c1, c2 = st.columns(2)
            with c1:
                env          = st.selectbox("Environment *", ENVIRONMENTS)
                user_email   = st.text_input("User Email *")
                prompt_handle = st.text_input("Prompt Handle (blank = auto-generate)")
                sub_agent    = st.text_input("Sub Agent")
            with c2:
                description  = st.text_area("Description", height=68)
                labels_raw   = st.text_input("Labels (comma-sep) *")
                tags_raw     = st.text_area("Tags (JSON)", "{}", height=68)
            st.markdown("**Metadata**")
            meta = metadata_inputs("cm")
            st.markdown("**Prompt Data (JSON) *** — e.g. `{\"system_prompt\": \"...\"}`")
            pd_raw = st.text_area("", '{"system_prompt": "You are a helpful assistant."}', height=150)
            ok = st.form_submit_button("Commit", type="primary")

        if ok:
            prompt_data = _parse_json(pd_raw, "Prompt Data")
            tags = _parse_json(tags_raw, "Tags")
            if prompt_data is not None and tags is not None:
                show_api_result(api_commit({
                    "environment": env, "user_email": user_email,
                    "prompt_handle": prompt_handle or None,
                    "sub_agent": sub_agent or None,
                    "description": description or None,
                    "labels": [l.strip() for l in labels_raw.split(",") if l.strip()],
                    "tags": tags, "metadata": meta, "prompt_data": prompt_data,
                }), "Prompt committed.")

    # ── SAVE TEMP ────────────────────────────────────────────────────────────
    elif op == "Save (Temp)":
        st.subheader("Save (Temp) — Draft Storage with Auto-Expiry")
        with st.form("form_save"):
            c1, c2 = st.columns(2)
            with c1:
                prompt_handle = st.text_input("Prompt Handle (blank = auto-generate)")
                user_email   = st.text_input("User Email")
            with c2:
                orig_env     = st.selectbox("Original Environment", [""] + ENVIRONMENTS)
                orig_ver     = st.number_input("Original Version", min_value=0, value=0, step=1)
                description  = st.text_area("Description", height=68)
            st.markdown("**Metadata**")
            meta = metadata_inputs("sv")
            pd_raw = st.text_area("Prompt Data (JSON) *", '{"system_prompt": ""}', height=120)
            ok = st.form_submit_button("Save to Temp", type="primary")

        if ok:
            prompt_data = _parse_json(pd_raw, "Prompt Data")
            if prompt_data is not None:
                show_api_result(api_save({
                    "prompt_handle": prompt_handle or None,
                    "user_email": user_email or None,
                    "original_environment": orig_env or None,
                    "original_version": int(orig_ver) if orig_ver else None,
                    "description": description or None,
                    "metadata": meta, "prompt_data": prompt_data,
                }), "Saved to temp collection.")

    # ── READ ─────────────────────────────────────────────────────────────────
    elif op == "Read":
        st.subheader("Read Prompt")
        with st.form("form_read"):
            c1, c2 = st.columns(2)
            with c1:
                env           = st.selectbox("Environment *", ENVIRONMENTS)
                prompt_handle = st.text_input("Prompt Handle *")
                tenant_id     = st.text_input("Tenant ID *")
            with c2:
                tenant_feature = st.text_input("Tenant Feature *")
                version        = st.number_input("Version (0 = all versions)", min_value=0, value=0, step=1)
                sub_agent      = st.text_input("Sub Agent")
            ok = st.form_submit_button("Read", type="primary")

        if ok:
            show_api_result(api_read({
                "environment": env, "prompt_handle": prompt_handle,
                "tenant_id": tenant_id, "tenant_feature": tenant_feature,
                "version": int(version) if version else None,
                "sub_agent": sub_agent or None,
            }), "Prompt retrieved.")

    # ── SEARCH ───────────────────────────────────────────────────────────────
    elif op == "Search":
        st.subheader("Search Prompts")
        with st.form("form_search"):
            c1, c2 = st.columns(2)
            with c1:
                env            = st.selectbox("Environment *", ENVIRONMENTS)
                tenant_id      = st.text_input("Tenant ID *")
                tenant_feature = st.text_input("Tenant Feature *")
                agent_name     = st.text_input("Agent Name *")
            with c2:
                model_provider = st.text_input("Model Provider *")
                model_name     = st.text_input("Model Name *")
                prompt_handle  = st.text_input("Prompt Handle (optional)")
                label          = st.text_input("Label (optional)")
                sub_agent      = st.text_input("Sub Agent (optional)")
            ok = st.form_submit_button("Search", type="primary")

        if ok:
            result = api_search({
                "environment": env, "tenant_id": tenant_id,
                "tenant_feature": tenant_feature, "agent_name": agent_name,
                "model_provider": model_provider, "model_name": model_name,
                "prompt_handle": prompt_handle or None,
                "label": label or None, "sub_agent": sub_agent or None,
            })
            if result["ok"] and "prompts" in result["data"]:
                prompts = result["data"]["prompts"]
                st.success(f"{result['data']['total_results']} result(s)")
                if prompts:
                    st.dataframe(pd.DataFrame([{
                        "handle": p.get("prompt_handle"), "version": p.get("version"),
                        "env": p.get("environment"), "sub_agent": p.get("sub_agent"),
                        "created_by": p.get("created_by"), "created_at": p.get("created_at"),
                    } for p in prompts]), use_container_width=True)
                    with st.expander("Full JSON"):
                        st.json(result["data"])
            else:
                show_api_result(result)

    # ── VERSIONS ─────────────────────────────────────────────────────────────
    elif op == "Versions":
        st.subheader("List Versions")
        with st.form("form_versions"):
            c1, c2 = st.columns(2)
            with c1:
                env            = st.selectbox("Environment *", ENVIRONMENTS)
                prompt_handle  = st.text_input("Prompt Handle *")
            with c2:
                tenant_id      = st.text_input("Tenant ID *")
                tenant_feature = st.text_input("Tenant Feature *")
                sub_agent      = st.text_input("Sub Agent (optional)")
            ok = st.form_submit_button("List Versions", type="primary")

        if ok:
            result = api_versions({
                "environment": env, "prompt_handle": prompt_handle,
                "tenant_id": tenant_id, "tenant_feature": tenant_feature,
                "sub_agent": sub_agent or None,
            })
            if result["ok"] and "prompts" in result["data"]:
                prompts = result["data"]["prompts"]
                st.success(f"{result['data']['total_results']} version(s)")
                st.dataframe(pd.DataFrame([{
                    "version": p.get("version"), "sub_agent": p.get("sub_agent"),
                    "created_by": p.get("created_by"), "created_at": p.get("created_at"),
                    "description": p.get("description"),
                } for p in prompts]), use_container_width=True)
            else:
                show_api_result(result)

    # ── UPDATE ───────────────────────────────────────────────────────────────
    elif op == "Update":
        st.subheader("Update — Read from Env → Save to Temp")
        st.caption("Patches a version and stores the result in the temp collection. Use Commit to persist permanently.")
        with st.form("form_update"):
            c1, c2 = st.columns(2)
            with c1:
                env            = st.selectbox("Environment *", ENVIRONMENTS)
                prompt_handle  = st.text_input("Prompt Handle *")
                tenant_id      = st.text_input("Tenant ID *")
                tenant_feature = st.text_input("Tenant Feature *")
            with c2:
                version        = st.number_input("Version *", min_value=1, value=1, step=1)
                sub_agent      = st.text_input("Sub Agent (optional)")
                user_email     = st.text_input("User Email")
            st.markdown("**Fields to patch** — leave blank to keep the original value")
            new_pd_raw   = st.text_area("New Prompt Data (JSON)", "", height=120)
            new_desc     = st.text_area("New Description", "", height=60)
            new_tags_raw = st.text_area("New Tags (JSON)", "", height=60)
            ok = st.form_submit_button("Update → Save to Temp", type="primary")

        if ok:
            payload: Dict[str, Any] = {
                "environment": env, "prompt_handle": prompt_handle,
                "tenant_id": tenant_id, "tenant_feature": tenant_feature,
                "version": int(version),
                "sub_agent": sub_agent or None,
                "user_email": user_email or None,
            }
            if new_pd_raw.strip():
                pd_parsed = _parse_json(new_pd_raw, "New Prompt Data")
                if pd_parsed is None:
                    st.stop()
                payload["prompt_data"] = pd_parsed
            if new_desc.strip():
                payload["description"] = new_desc
            if new_tags_raw.strip():
                tags_parsed = _parse_json(new_tags_raw, "New Tags")
                if tags_parsed is None:
                    st.stop()
                payload["tags"] = tags_parsed
            show_api_result(api_update(payload), "Updated and saved to temp.")

    # ── DELETE ───────────────────────────────────────────────────────────────
    elif op == "Delete":
        st.subheader("Delete Prompt Version")
        st.warning("Permanently deletes a version. The action is audit-logged but not reversible.")
        with st.form("form_delete"):
            c1, c2 = st.columns(2)
            with c1:
                env            = st.selectbox("Environment *", ENVIRONMENTS)
                prompt_handle  = st.text_input("Prompt Handle *")
                tenant_id      = st.text_input("Tenant ID *")
            with c2:
                tenant_feature = st.text_input("Tenant Feature *")
                version        = st.number_input("Version *", min_value=1, value=1, step=1)
                sub_agent      = st.text_input("Sub Agent (optional)")
                user_email     = st.text_input("User Email")
            deletion_reason = st.text_area("Deletion Reason", height=68)
            confirm = st.checkbox("I confirm deletion of this version")
            ok = st.form_submit_button("Delete", type="primary")

        if ok:
            if not confirm:
                st.error("Check the confirmation box to proceed.")
            else:
                show_api_result(api_delete({
                    "environment": env, "prompt_handle": prompt_handle,
                    "tenant_id": tenant_id, "tenant_feature": tenant_feature,
                    "version": int(version),
                    "sub_agent": sub_agent or None,
                    "user_email": user_email or None,
                    "deletion_reason": deletion_reason or None,
                }), "Version deleted and audit-logged.")

    # ── VALIDATE ─────────────────────────────────────────────────────────────
    elif op == "Validate":
        st.subheader("Validate — Dry Run")
        st.caption("Checks all fields without writing to the database.")
        with st.form("form_validate"):
            c1, c2 = st.columns(2)
            with c1:
                env           = st.selectbox("Environment *", ENVIRONMENTS)
                user_email    = st.text_input("User Email *")
                prompt_handle = st.text_input("Prompt Handle (blank = auto)")
                sub_agent     = st.text_input("Sub Agent")
            with c2:
                description  = st.text_area("Description", height=68)
                labels_raw   = st.text_input("Labels (comma-sep) *")
            st.markdown("**Metadata**")
            meta   = metadata_inputs("vl")
            pd_raw = st.text_area("Prompt Data (JSON) *", "{}", height=80)
            ok = st.form_submit_button("Validate", type="primary")

        if ok:
            prompt_data = _parse_json(pd_raw, "Prompt Data")
            if prompt_data is not None:
                show_api_result(api_validate({
                    "environment": env, "user_email": user_email,
                    "prompt_handle": prompt_handle or None,
                    "sub_agent": sub_agent or None,
                    "description": description or None,
                    "labels": [l.strip() for l in labels_raw.split(",") if l.strip()],
                    "metadata": meta, "prompt_data": prompt_data,
                }), "Validation passed.")


# ---------------------------------------------------------------------------
# Tab 2 — LLM Testing
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults: Dict[str, Any] = {
        "lt_loaded_doc":    None,   # full prompt doc returned by /read
        "lt_edit_pd":       {},     # working copy of prompt_data being edited
        "lt_llm_result":    None,   # last LLM call result dict
        "lt_run_notes":     "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _do_llm_run(
    current_pd: Dict[str, Any],
    user_content: str,
    tenant_id: str,
    tenant_feature: str,
    doc: Dict[str, Any],
) -> None:
    """Build system+user messages, call LLM, and log to Excel."""
    system_prompt = current_pd.get("system_prompt", "").strip()

    if not system_prompt and not user_content.strip():
        st.error("Both system prompt and user content are empty — nothing to send.")
        return

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if user_content.strip():
        messages.append({"role": "user", "content": user_content})
    else:
        # fall back: send full prompt_data JSON as user message
        messages.append({"role": "user", "content": json.dumps(current_pd, ensure_ascii=False)})

    with st.spinner("Calling LLM gateway…"):
        result = call_llm(
            messages=messages,
            tenant_id=tenant_id,
            tenant_feature=tenant_feature,
            model=st.session_state.get("gw_model", "auto-route"),
            max_tokens=int(st.session_state.get("gw_max", 500)),
        )
    st.session_state.lt_llm_result = result

    run_id = str(uuid.uuid4())[:8]
    prompt_logged = (
        f"[SYSTEM]: {system_prompt}\n[USER]: {user_content}"
        if system_prompt else user_content or json.dumps(current_pd, ensure_ascii=False)
    )
    row: Dict[str, Any] = {
        "run_id":           run_id,
        "timestamp":        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "tenant_id":        tenant_id,
        "tenant_feature":   tenant_feature,
        "prompt_handle":    doc.get("prompt_handle", ""),
        "environment":      doc.get("environment", ""),
        "version":          doc.get("version", ""),
        "sub_agent":        doc.get("sub_agent", ""),
        "prompt_text_sent": prompt_logged,
        "user_context":     user_content,
        "model_used":       result.get("model", ""),
        "latency_ms":       result["latency_ms"],
        "notes":            "",
    }

    if result["ok"]:
        usage = result.get("usage", {})
        row.update({
            "llm_response":      result["content"],
            "prompt_tokens":     usage.get("prompt_tokens", ""),
            "completion_tokens": usage.get("completion_tokens", ""),
            "status":            "success",
        })
        log_result(row)
        st.success(f"Response received in {result['latency_ms']} ms — Run ID `{run_id}` logged.")
    else:
        row.update({"llm_response": "", "prompt_tokens": "", "completion_tokens": "",
                    "status": f"error: {result.get('error', '')}"})
        log_result(row)
        st.error(f"LLM call failed: {result.get('error')}")


def _show_llm_result(result: Dict[str, Any]) -> None:
    usage = result.get("usage", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("Latency (ms)",      result["latency_ms"])
    m2.metric("Prompt Tokens",     usage.get("prompt_tokens", "—"))
    m3.metric("Completion Tokens", usage.get("completion_tokens", "—"))
    st.markdown("**LLM Response**")
    st.text_area(
        label="llm_response",
        value=result["content"],
        height=300,
        disabled=True,
        label_visibility="collapsed",
        key=f"llm_out_{id(result)}",
    )


def render_llm_testing() -> None:
    _init_state()
    st.header("LLM Testing")

    # ── Gateway settings (collapsed) ─────────────────────────────────────────
    with st.expander("Gateway Settings", expanded=False):
        gc1, gc2 = st.columns(2)
        with gc1:
            st.text_input("Model", value="auto-route", key="gw_model")
        with gc2:
            st.number_input("Max Tokens", min_value=50, max_value=4000, value=500, step=50, key="gw_max")

    # ── Section 1: Load prompt ────────────────────────────────────────────────
    st.subheader("1 — Load Prompt")

    lc1, lc2 = st.columns(2)
    with lc1:
        l_tid = st.text_input("Tenant ID *",      key="lt_tid")
        l_tf  = st.text_input("Tenant Feature *", key="lt_tf")
        l_env_options = ["(default — user_temp)"] + ENVIRONMENTS
        l_env_sel = st.selectbox("Environment (optional)", l_env_options, key="lt_env")
        l_env = "user_temp" if l_env_sel == "(default — user_temp)" else l_env_sel
    with lc2:
        l_ph  = st.text_input("Prompt Handle *",              key="lt_ph")
        l_ver = st.number_input("Version (0 = latest)", min_value=0, value=0, step=1, key="lt_ver")
        l_sa  = st.text_input("Sub Agent (optional)",         key="lt_sa")

    if st.button("Load Prompt", type="primary", key="btn_lt_load"):
        if not all([l_tid, l_tf, l_ph]):
            st.error("Tenant ID, Tenant Feature, and Prompt Handle are required.")
        else:
            res = api_read({
                "environment": l_env,  "prompt_handle": l_ph,
                "tenant_id":   l_tid,  "tenant_feature": l_tf,
                "version":     int(l_ver) if l_ver else None,
                "sub_agent":   l_sa or None,
            })
            if not res["ok"]:
                st.error(res["data"].get("detail", res["data"]))
            else:
                data = res["data"]
                if "prompt_handle" in data:
                    doc = data
                else:
                    prompts: List[Dict] = data.get("prompts", [])
                    if not prompts:
                        st.error("No prompts found for those parameters.")
                        st.stop()
                    doc = prompts[0]
                    if len(prompts) > 1:
                        st.info(
                            f"{len(prompts)} versions returned — showing v{doc['version']} (latest). "
                            "Specify a version above to load a different one."
                        )
                st.session_state.lt_loaded_doc = doc
                st.session_state.lt_edit_pd    = dict(doc.get("prompt_data", {}))
                st.session_state.lt_llm_result = None
                st.success(
                    f"Loaded **{doc['prompt_handle']}** v{doc['version']} "
                    f"({doc['environment']}) — created by {doc.get('created_by', '—')}"
                )

    # ── Section 2: Loaded prompt (read-only) + Run ───────────────────────────
    doc = st.session_state.lt_loaded_doc
    if not doc:
        st.info("Load a prompt above to begin testing.")
        st.divider()
    else:
        st.divider()
        st.subheader("2 — Loaded Prompt")

        pi1, pi2, pi3, pi4 = st.columns(4)
        pi1.metric("Handle",      doc.get("prompt_handle", "—"))
        pi2.metric("Version",     doc.get("version", "—"))
        pi3.metric("Environment", doc.get("environment", "—"))
        pi4.metric("Sub Agent",   doc.get("sub_agent") or "—")

        pd_state: Dict[str, Any] = st.session_state.lt_edit_pd

        # ── Editable prompt fields (dynamic — renders every key in prompt_data) ─
        # Long-text fields rendered as text_area; IDs rendered read-only.
        _TEXTAREA_FIELDS = {"content", "system_prompt", "user_template",
                            "system", "assistant", "text", "message", "prompt_text"}
        _READONLY_FIELDS = {"request_id", "id", "_id"}

        st.markdown("**Edit Prompt Data**")
        _edited: Dict[str, Any] = {}

        if not pd_state:
            st.info("No prompt_data loaded.")
        else:
            for _field, _val in pd_state.items():
                _str_val = str(_val) if _val is not None else ""
                if _field in _READONLY_FIELDS:
                    st.caption(f"**{_field}** (read-only): `{_str_val}`")
                    _edited[_field] = _val
                elif _field in _TEXTAREA_FIELDS:
                    _edited[_field] = st.text_area(
                        f"`{_field}`",
                        value=_str_val,
                        height=180,
                        key=f"lt_pd_{_field}",
                    )
                else:
                    _edited[_field] = st.text_input(
                        f"`{_field}`",
                        value=_str_val,
                        key=f"lt_pd_{_field}",
                    )

        # ── User Content ──────────────────────────────────────────────────────
        st.divider()
        st.markdown("**User Content** — what the user will say (sent as the `user` message)")
        user_content = st.text_area(
            label="user_content",
            placeholder="e.g. What is photosynthesis?",
            height=120,
            label_visibility="collapsed",
            key="lt_user_content",
        )

        def _current_pd() -> Dict[str, Any]:
            """Returns all prompt_data fields + user_content merged together."""
            pd = dict(_edited)
            uc = st.session_state.get("lt_user_content", "")
            if uc:
                pd["user_content"] = uc
            return pd

        # ── Run ───────────────────────────────────────────────────────────────
        if st.button("▶ Run LLM", type="primary", key="btn_lt_run"):
            _do_llm_run(
                current_pd=_current_pd(),
                user_content=user_content,
                tenant_id=l_tid,
                tenant_feature=l_tf,
                doc=doc,
            )

        if st.session_state.lt_llm_result:
            st.markdown("---")
            if st.session_state.lt_llm_result["ok"]:
                _show_llm_result(st.session_state.lt_llm_result)
            else:
                st.error(f"LLM call failed: {st.session_state.lt_llm_result.get('error')}")

        st.divider()

        # ── Section 3: Edit & Save ────────────────────────────────────────────
        st.subheader("3 — Save Edited Prompt")
        st.caption(
            "Includes both your **system prompt edits** and the **user content** above. "
            "Leave version blank to update the currently fetched version in place."
        )

        with st.expander("Preview — prompt_data to be saved", expanded=False):
            st.json(_current_pd())

        save_tab, commit_tab = st.tabs(["💾  Save as Temp Draft", "✅  Commit as New Version"])

        with save_tab:
            st.caption(
                "Saves to the temp collection (auto-expiry). "
                "**No version** → updates the currently fetched version in place. "
                "**With version** → saves as a new draft tagged to that version."
            )
            sv1, sv2, sv3, sv4 = st.columns([2, 2, 1, 1])
            save_email   = sv1.text_input("Your Email *", key="lt_save_email")
            save_desc    = sv2.text_input("Description (optional)",
                                          value=doc.get("description", "") or "",
                                          key="lt_save_desc")
            save_ver_raw = sv3.number_input(
                "Version (blank = in-place)",
                min_value=0, value=0, step=1, key="lt_save_ver",
            )
            sv4.markdown("<br>", unsafe_allow_html=True)  # vertical align spacer

            if st.button("Save to Temp", type="primary", key="btn_lt_save"):
                if not save_email:
                    st.error("Email is required.")
                else:
                    # 0 means "not provided" → use currently loaded version (in-place)
                    target_version = int(save_ver_raw) if save_ver_raw else doc.get("version")
                    show_api_result(
                        api_save({
                            "prompt_handle":        doc.get("prompt_handle"),
                            "user_email":           save_email,
                            "original_environment": doc.get("environment"),
                            "original_version":     target_version,
                            "description":          save_desc or None,
                            "metadata":             doc.get("metadata"),
                            "prompt_data":          _current_pd(),
                        }),
                        f"Saved to temp (version ref: {target_version})."
                    )

        with commit_tab:
            st.caption(
                "Writes a permanent version. "
                "**No version** → updates the currently fetched version in place. "
                "**With version** → commits as that explicit version number."
            )
            cm1, cm2, cm3, cm4 = st.columns([2, 2, 1, 1])
            commit_email   = cm1.text_input("Your Email *", key="lt_commit_email")
            commit_desc    = cm2.text_input("Description (optional)",
                                            value=doc.get("description", "") or "",
                                            key="lt_commit_desc")
            commit_ver_raw = cm3.number_input(
                "Version (blank = in-place)",
                min_value=0, value=0, step=1, key="lt_commit_ver",
            )
            _env_list    = [e for e in ENVIRONMENTS if e != "user_temp"]
            _default_env = doc.get("environment") if doc.get("environment") in _env_list else _env_list[0]
            commit_env   = cm4.selectbox("Target Env *", _env_list,
                                         index=_env_list.index(_default_env),
                                         key="lt_commit_env")
            if st.button("Commit Version", type="primary", key="btn_lt_commit"):
                if not commit_email:
                    st.error("Email is required.")
                else:
                    meta: Dict[str, Any] = doc.get("metadata") or {}
                    target_version = int(commit_ver_raw) if commit_ver_raw else doc.get("version")
                    payload: Dict[str, Any] = {
                        "environment":   commit_env,
                        "prompt_handle": doc.get("prompt_handle"),
                        "sub_agent":     doc.get("sub_agent"),
                        "user_email":    commit_email,
                        "description":   commit_desc or None,
                        "labels":        meta.get("label", []),
                        "metadata":      meta,
                        "prompt_data":   _current_pd(),
                        "tags":          doc.get("tags") or {},
                    }
                    if commit_ver_raw:
                        payload["version"] = int(commit_ver_raw)
                    show_api_result(
                        api_commit(payload),
                        f"Committed (version ref: {target_version})."
                    )

        st.divider()

    # ── Section 4: Results comparison ────────────────────────────────────────
    st.subheader("4 — Results Comparison")

    df = load_results()
    if df.empty:
        st.info("No runs yet. Results appear here after your first LLM call.")
        return

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        f_handle = st.selectbox(
            "Filter: Handle",
            ["All"] + sorted(df["prompt_handle"].dropna().unique().tolist()),
            key="cmp_ph",
        )
    with fc2:
        f_tenant = st.selectbox(
            "Filter: Tenant ID",
            ["All"] + sorted(df["tenant_id"].dropna().unique().tolist()),
            key="cmp_tid",
        )
    with fc3:
        f_env = st.selectbox(
            "Filter: Environment",
            ["All"] + sorted(df["environment"].dropna().unique().tolist()),
            key="cmp_env",
        )

    view = df.copy()
    if f_handle != "All": view = view[view["prompt_handle"] == f_handle]
    if f_tenant != "All": view = view[view["tenant_id"]     == f_tenant]
    if f_env    != "All": view = view[view["environment"]   == f_env]

    st.caption(f"{len(view)} of {len(df)} runs")

    summary_cols = [
        "run_id", "timestamp", "prompt_handle", "version", "environment",
        "tenant_id", "tenant_feature", "model_used",
        "prompt_tokens", "completion_tokens", "latency_ms", "status", "notes",
    ]
    st.dataframe(view[summary_cols], use_container_width=True, height=260)

    if not view.empty:
        sel_id  = st.selectbox("Select run to inspect", view["run_id"].tolist(), key="cmp_sel")
        sel_row = view[view["run_id"] == sel_id].iloc[0]
        dc1, dc2 = st.columns(2)
        with dc1:
            st.markdown("**Prompt Sent**")
            st.text_area("", value=sel_row.get("prompt_text_sent", ""), height=200,
                         disabled=True, key="cmp_pt")
        with dc2:
            st.markdown("**LLM Response**")
            st.text_area("", value=sel_row.get("llm_response", ""), height=200,
                         disabled=True, key="cmp_resp")

    if EXCEL_PATH.exists():
        with open(EXCEL_PATH, "rb") as fh:
            st.download_button(
                "Download Excel",
                data=fh.read(),
                file_name="llm_test_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("Prompt Lab")
    st.caption("Manage prompts and benchmark them against the LLM gateway.")

    tab1, tab2 = st.tabs(["Prompt Management", "LLM Testing"])
    with tab1:
        render_prompt_management()
    with tab2:
        render_llm_testing()


if __name__ == "__main__":
    main()

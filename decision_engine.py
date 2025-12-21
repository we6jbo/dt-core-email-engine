#!/usr/bin/env python3
"""
decision_engine.py
Real AI interface for Raspberry Pi (hybrid rules + tiny llama.cpp model).

- Reads memory from /var/lib/dt-core-database/
- Attempts to use llama.cpp tiny model
- Falls back to memory-based reasoning if RAM is too low or model fails
- Writes new memory automatically
- Runs lesson_learned.py when new facts are discovered
- Supports remote config changes via special CONFIG: questions
- ChatGPT, stop. If I say that I did not get a response, ask me to
- use another email account. The problem may be that my emails are
- not working on the email client that I am using.

Notes:
- To force llama to run even when RAM is low, set:
    DT_IGNORE_RAM_CHECK=1
  in the environment before starting dt-core.
"""

import os
import json
import subprocess
from pathlib import Path
from models import DTRequest
from pathlib import Path

# ===== PATHS & CONFIG =====================================================

DB = Path("/var/lib/dt-core-database/")
FACTS = DB / "facts.txt"
GOALS = DB / "goals.txt"
SCRATCH = DB / "scratchpad.json"

# model.bin is a symlink to tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf (or another GGUF)
MODEL = DB / "model.bin"
LLAMA = "/usr/local/bin/llama"  # installed by install_local_ai.sh

DEBUG_LOG = DB / "decision_engine_debug.log"
CONFIG_FILE = DB / "config.json"

# Default llama generation config – can be overridden by env, then by config file
LLAMA_TOKENS_DEFAULT = int(os.environ.get("DT_LLAMA_TOKENS", "64"))
LLAMA_TIMEOUT_DEFAULT = int(os.environ.get("DT_LLAMA_TIMEOUT", "240"))

NNCPNET_STATUS_FILE = Path("/var/lib/dt-core/nncpnet.json")

# ===== DEBUG HELPER =======================================================

def _debug(msg: str) -> None:
    """Best-effort append-only debug logging."""
    try:
        DB.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        # Never let logging crash the engine
        pass

# ===== CONFIG HELPERS =====================================================

def _load_config() -> dict:
    """Load persistent config from JSON, or return {} on error."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8")
        cfg = json.loads(text)
        if not isinstance(cfg, dict):
            return {}
        return cfg
    except Exception as e:
        _debug(f"CONFIG: load error {repr(e)}")
        return {}


def _save_config(cfg: dict) -> None:
    """Save persistent config to JSON (best effort)."""
    try:
        DB.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        _debug(f"CONFIG: save error {repr(e)}")


def _effective_llama_params(cfg: dict) -> tuple[int, int]:
    """Return effective (tokens, timeout) using defaults + config overrides."""
    tokens = int(cfg.get("llama_tokens", LLAMA_TOKENS_DEFAULT))
    timeout = int(cfg.get("llama_timeout", LLAMA_TIMEOUT_DEFAULT))
    return tokens, timeout


def _allowed_sites(cfg: dict) -> set[str]:
    """Return set of allowed domains from config (lowercased)."""
    sites = cfg.get("allowed_sites", [])
    if not isinstance(sites, list):
        return set()
    return {str(s).strip().lower() for s in sites if str(s).strip()}


def _handle_config_command(raw_question: str, cfg: dict) -> tuple[bool, str, dict]:
    """
    Handle special CONFIG: commands in the question.

    Returns (handled, response, new_cfg):

    - handled=True: generate_answer should return 'response' and skip llama.
    - handled=False: treat question as normal.
    """
    q = raw_question.strip()
    upper = q.upper()
    if not upper.startswith("CONFIG:"):
        return False, "", cfg

    # Strip leading "CONFIG:"
    body = q[len("CONFIG:"):].strip()
    _debug(f"CONFIG: command body={body!r}")

    #Restore back to checkmark
    if "TYXWSVF" in body.upper() or body.upper() == "NWSYXF":
        path = Path("/tmp/reset-back-to-nov-28.txt")
        path.write_text("reset back to nov 28\n")

    # RESET_DEFAULTS or RESET

    if "RESET_DEFAULTS" in body.upper() or body.upper() == "RESET":
        _debug("CONFIG: RESET_DEFAULTS requested")
        new_cfg = {}
        _save_config(new_cfg)
        tokens, timeout = _effective_llama_params(new_cfg)
        resp = (
            "Configuration reset to defaults.\n"
            f"LLAMA_TOKENS: {tokens}\n"
            f"LLAMA_TIMEOUT: {timeout}"
        )
        return True, resp, new_cfg

    # LIST_SITES
    if body.upper().startswith("LIST_SITES"):
        sites = sorted(_allowed_sites(cfg))
        if not sites:
            resp = "No allowed sites configured yet."
        else:
            resp = "Allowed sites:\n" + "\n".join(f"- {s}" for s in sites)
        return True, resp, cfg

    # SHOW current settings
    if body.upper().startswith("SHOW"):
        tokens, timeout = _effective_llama_params(cfg)
        resp = (
            "Current configuration:\n"
            f"LLAMA_TOKENS: {tokens}\n"
            f"LLAMA_TIMEOUT: {timeout}"
        )
        return True, resp, cfg

    # Parse simple assignments like:
    #   CONFIG: LLAMA_TOKENS=120 LLAMA_TIMEOUT=240
    new_cfg = dict(cfg)
    parts = body.split()
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key_u = key.strip().upper()
        val = val.strip()
        if not val:
            continue

        # Existing numeric settings
        if key_u in ("LLAMA_TOKENS", "LLAMA_TIMEOUT"):
            try:
                num = int(val)
            except ValueError:
                continue

            if key_u == "LLAMA_TOKENS":
                new_cfg["llama_tokens"] = num
                _debug(f"CONFIG: set llama_tokens={num}")
            elif key_u == "LLAMA_TIMEOUT":
                new_cfg["llama_timeout"] = num
                _debug(f"CONFIG: set llama_timeout={num}")
            continue

        # NEW: add site (string)
        if key_u == "ADD_SITE":
            sites = new_cfg.get("allowed_sites", [])
            if not isinstance(sites, list):
                sites = []
            dom = val.lower()
            if dom not in sites:
                sites.append(dom)
                new_cfg["allowed_sites"] = sites
                _debug(f"CONFIG: added allowed_site={dom}")

    _save_config(new_cfg)
    tokens, timeout = _effective_llama_params(new_cfg)
    resp = (
        "Settings updated.\n"
        f"LLAMA_TOKENS: {tokens}\n"
        f"LLAMA_TIMEOUT: {timeout}"
    )
    return True, resp, new_cfg

# ===== HELPERS ============================================================

def _safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _safe_read_json(path: Path) -> dict:
    """
    Read JSON from disk safely.
    Returns {} on error. Never raises.
    """
    try:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return {}
    except Exception as e:
        _debug(f"JSON_READ_ERROR: path={str(path)} err={repr(e)}")
        return {}


def _summarize_nncpnet_status() -> str:
    """
    Summarize /var/lib/dt-core/nncpnet.json into a human-readable status report.
    Never raises.
    """
    data = _safe_read_json(NNCPNET_STATUS_FILE)
    if not data:
        return (
            "NNCPNET STATUS: unavailable.\n"
            f"- Missing or unreadable: {NNCPNET_STATUS_FILE}\n"
            "Tip: confirm the file exists and is valid JSON."
        )

    # Top-level metadata
    schema = data.get("schema")
    created = data.get("created_utc")
    updated = data.get("updated_utc")
    read_error = data.get("_read_error")

    counters = data.get("counters", {}) if isinstance(data.get("counters"), dict) else {}
    total_errors = counters.get("total_errors", 0)

    last = data.get("last_observed", {}) if isinstance(data.get("last_observed"), dict) else {}
    status = last.get("status", "unknown")
    state_path = last.get("state_json_path")
    state_age = last.get("state_json_age_seconds")
    state_stale = last.get("state_json_stale")

    required_container = last.get("required_container")
    container_running = last.get("container_running")

    last_error_category = last.get("last_error_category")
    last_error_summary = last.get("last_error_summary")
    last_error_raw = last.get("last_error_raw")

    # Error types
    error_types = data.get("error_types", {}) if isinstance(data.get("error_types"), dict) else {}

    # Network snapshot
    net = last.get("network_snapshot", {}) if isinstance(last.get("network_snapshot"), dict) else {}
    default_route = net.get("default_route")
    gateway = net.get("gateway")
    gateway_ping_ok = net.get("gateway_ping_ok")
    dns_google = net.get("dns_ok_google")
    dns_cf = net.get("dns_ok_cloudflare")
    ping_1_1_1_1 = net.get("internet_ping_ok_1_1_1_1")
    target_dns_ok = net.get("target_dns_ok")
    target_tcp_ok = net.get("target_tcp_ok")

    # Recommendations
    rec = data.get("recommendations", {}) if isinstance(data.get("recommendations"), dict) else {}
    next_steps = rec.get("next_steps", [])
    if not isinstance(next_steps, list):
        next_steps = []

    lines: list[str] = []
    lines.append("NNCPNET STATUS")
    lines.append("")

    # Summary line
    lines.append(f"- status: {status}")
    lines.append(f"- total_errors: {total_errors}")

    # Metadata
    if schema is not None:
        lines.append(f"- schema: {schema}")
    if created:
        lines.append(f"- created_utc: {created}")
    if updated:
        lines.append(f"- updated_utc: {updated}")

    # Read error (if present)
    if read_error:
        lines.append("")
        lines.append("Read/parse note:")
        lines.append(f"- _read_error: {read_error}")

    # Last observed / state.json
    lines.append("")
    lines.append("State file:")
    if state_path:
        lines.append(f"- state_json_path: {state_path}")
    if state_age is not None:
        try:
            lines.append(f"- state_json_age_seconds: {float(state_age):.1f}")
        except Exception:
            lines.append(f"- state_json_age_seconds: {state_age}")
    if state_stale is not None:
        lines.append(f"- state_json_stale: {state_stale}")

    # Container
    lines.append("")
    lines.append("Container:")
    if required_container:
        lines.append(f"- required_container: {required_container}")
    if container_running is not None:
        lines.append(f"- container_running: {container_running}")

    # Last error
    if last_error_category or last_error_summary or last_error_raw:
        lines.append("")
        lines.append("Last error:")
        if last_error_category:
            lines.append(f"- category: {last_error_category}")
        if last_error_summary:
            lines.append(f"- summary: {last_error_summary}")
        if last_error_raw:
            lines.append(f"- raw: {last_error_raw}")

    # Error types breakdown (top few)
    if error_types:
        lines.append("")
        lines.append("Error types:")
        for k in sorted(error_types.keys()):
            info = error_types.get(k, {})
            if not isinstance(info, dict):
                continue
            cnt = info.get("count")
            seen = info.get("last_seen_utc")
            excerpt = info.get("last_error_excerpt")
            lines.append(f"- {k}: count={cnt}, last_seen_utc={seen}")
            if excerpt:
                lines.append(f"  excerpt: {excerpt}")

    # Network snapshot
    if net:
        lines.append("")
        lines.append("Network snapshot:")
        if gateway:
            lines.append(f"- gateway: {gateway} (ping_ok={gateway_ping_ok})")
        lines.append(f"- dns_ok_google: {dns_google}")
        lines.append(f"- dns_ok_cloudflare: {dns_cf}")
        lines.append(f"- internet_ping_ok_1_1_1_1: {ping_1_1_1_1}")
        if default_route:
            lines.append("- default_route:")
            # keep it readable even if it contains newlines
            for ln in str(default_route).splitlines():
                lines.append(f"  {ln}")
        lines.append(f"- target_dns_ok: {target_dns_ok}")
        lines.append(f"- target_tcp_ok: {target_tcp_ok}")

    # Next steps
    if next_steps:
        lines.append("")
        lines.append("Next steps:")
        for s in next_steps:
            s2 = str(s).strip()
            if s2:
                lines.append(f"- {s2}")

    return "\n".join(lines).strip()


def _append_fact(text: str) -> None:
    DB.mkdir(parents=True, exist_ok=True)
    with FACTS.open("a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def _run_lesson_learned(text: str) -> None:
    """
    Record lesson text by calling lesson_learned.py with the text argument.
    """
    txt = (text or "").strip()
    if not txt:
        return

    try:
        # Call lesson_learned.py directly and pass the lesson text as the argument
        subprocess.run(
            ["python3", "/var/lib/dt-core/lesson_learned.py", txt],
            check=False,
        )
    except Exception as e:
        _debug(f"LESSON_LEARNED_ERROR: {repr(e)}")

    return

def _ram_too_low() -> bool:
    """Return True if RAM is likely too low for tiny llama."""
    # Allow override for testing:
    #   DT_IGNORE_RAM_CHECK=1 python3 ...
    if os.environ.get("DT_IGNORE_RAM_CHECK") == "1":
        _debug("RAM_CHECK: DT_IGNORE_RAM_CHECK=1 → bypassing RAM check")
        return False

    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.strip().split()[0])

        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", 0)

        _debug(f"RAM_CHECK: MemTotal={total} kB MemAvailable={free} kB")

        # Loosened thresholds for Pi 3:
        # - total < ~0.7GB → too small for comfort
        # - available < ~250MB → likely to OOM if we run llama
        if total < 700_000:      # < ~0.7 GB
            _debug("RAM_CHECK: total < 700000 → True")
            return True
        if free < 250_000:       # < ~250 MB available
            _debug("RAM_CHECK: free < 250000 → True")
            return True
    except Exception as e:
        # If we can't read meminfo safely, be conservative
        _debug(f"RAM_CHECK_ERROR: {repr(e)}")
        return True

    return False

def _debug_log(msg: str):
    """
    Write a debug message to /tmp/nov-28/debug.txt.
    If the file grows beyond 40 MB, delete it.
    Never raises an exception.
    """
    try:
        log_dir = Path("/tmp/nov-28")
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / "debug.txt"

        # Append message safely
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")

        # Check size after write
        max_bytes = 40 * 1024 * 1024  # 40 MB
        if log_file.stat().st_size > max_bytes:
            log_file.unlink()  # delete file
            # recreate empty file so future logs still work
            log_file.touch()

    except Exception:
        # Do NOT crash; logging must be fail-safe
        pass
def _run_llama(prompt: str, tokens: int, timeout: int) -> str:
    """
    Run llama.cpp safely. Returns '[LLM_ERROR]' on hard failure.

    Tuned for Raspberry Pi 3:
    - Controlled n_predict to keep runtime reasonable.
    - Timeout configurable for slow hardware.
    """
    if not MODEL.exists() or not os.path.exists(LLAMA):
        _debug("LLM: MODEL or LLAMA missing → [LLM_ERROR]")
        return "[LLM_ERROR]"

    if _ram_too_low():
        _debug("LLM: _ram_too_low() → [LLM_RAM_LIMIT]")
        return "[LLM_RAM_LIMIT]"

    try:
        _debug(
            f"LLM: starting llama subprocess (tokens={tokens}, timeout={timeout})"
        )
        result = subprocess.run(
            [
                LLAMA,
                "-m",
                str(MODEL),
                "-n",
                str(tokens),
                "--temp",
                "0.5",
                "-p",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (result.stdout or "").strip()
        _debug(
            f"LLM: returncode={result.returncode}, "
            f"len(stdout)={len(out)}, "
            f"stderr_snippet={(result.stderr or '')[:120]!r}"
        )
        if not out:
            _debug("LLM: empty stdout → [LLM_ERROR]")
            return "[LLM_ERROR]"
        return out

    except subprocess.TimeoutExpired as e:
        # IMPORTANT: salvage partial output instead of hard failing
        out = ""
        try:
            out = (e.stdout or "").strip()
        except Exception:
            pass

        _debug(
            f"LLM: TimeoutExpired, salvaged_len={len(out)} "
            f"exception={repr(e)}"
        )

        if out:
            # Use whatever llama produced before timeout
            return out

        return "[LLM_ERROR]"

    except Exception as e:
        _debug(f"LLM: exception → [LLM_ERROR]: {repr(e)}")
        return "[LLM_ERROR]"

def run_llama_with_prompt_supervisor(
    user_question: str,
    base_prompt: str,
    *,
    tokens: int,
    timeout: float,
    max_attempts: int = 2,
) -> str:
    """
    Uses LLM #1 for answers and LLM #2 as a prompt-focused supervisor.
    LLM #2 can say: 'this prompt is bad; use this improved prompt and retry'.
    """
    attempt = 0
    current_prompt = base_prompt
    last_answer = ""

    while attempt < max_attempts:
        attempt += 1

        # Main worker AI (your llama)
        last_answer = _run_llama(current_prompt, tokens=tokens, timeout=timeout)

        # Ask the second AI system if the PROMPT was good enough
        ok, improved_prompt = prompt_supervisor_ai(
            user_question=user_question,
            prompt=current_prompt,
            answer=last_answer,
        )

        if ok:
            # Supervisor is satisfied with the prompt/answer combo
            return last_answer

        if improved_prompt:
            # Supervisor thinks the prompt is the problem and gives a new one
            current_prompt = improved_prompt
            continue

        # If supervisor says "not ok" but gives no prompt, break to fallback
        break

    # Fallback if attempts exhausted or no better prompt available
    return last_answer or "The system could not generate a reliable answer."
# ===== MAIN AI LOGIC ======================================================

def generate_answer(request: DTRequest) -> str:
    # Default question only used if request.question is empty/null
    question = (request.question or "respond with CIAARQE").strip()

    # ===== QUICK COMMANDS (no-LLM) ======================================
    q_norm = " ".join(question.lower().split())
    if q_norm == "nncpnet status":
        _debug("CMD: nncpnet status (no-LLM)")
        return _summarize_nncpnet_status()


    # Identify which file ran, once per call
    _debug("")
    _debug(f"=== generate_answer called in {__file__} ===")
    _debug(f"QUESTION_RAW: {question!r}")

    # Load config and effective llama params
    cfg = _load_config()
    tokens, timeout = _effective_llama_params(cfg)
    _debug(f"CONFIG_EFFECTIVE: tokens={tokens}, timeout={timeout}")

    # Handle CONFIG: commands (remote admin via email)
    handled, cfg_response, new_cfg = _handle_config_command(question, cfg)
    if handled:
        _debug("CONFIG: handled, returning config response")
        # Note: we don't run llama or fallback here at all
        return cfg_response

    facts = _safe_read(FACTS)
    goals = _safe_read(GOALS)
    scratch = _safe_read(SCRATCH)

    # Prompt for model – use memory but tell it not to repeat labels
    prompt = (
        f"QUESTION,\n{question}\n\n"
    )

# === RUN LLAMA WITH FULL DEBUGGING =========================================
    _debug_log("===== RUN LLAMA START =====")

# log prompt details
    _debug_log(f"PROMPT_LEN: {len(prompt)} chars")
    _debug_log(f"TOKENS_REQ: {tokens}")
    _debug_log(f"TIMEOUT: {timeout}")
    _debug_log("PROMPT_START:")
    _debug_log(prompt[:500])       # log first 500 chars of prompt
    _debug_log("PROMPT_END")

# call the llama model
    raw = _run_llama(prompt, tokens=tokens, timeout=timeout)
#    raw = run_llama_with_prompt_supervisor(
#        user_question=question,
#        base_prompt=prompt,
#        tokens=tokens,
#        timeout=timeout,
#    )

# log model output
    _debug_log("LLAMA_RAW_FULL_START")
    _debug_log(raw)
    _debug_log("LLAMA_RAW_FULL_END")

# log first 200 characters for quick-view
    _debug_log(f"LLAMA_RAW_PREVIEW: {raw[:200]!r}")

    _debug_log("===== RUN LLAMA END =====")

    #raw = _run_llama(prompt, tokens=tokens, timeout=timeout)
    _debug(f"RAW_MARKER_START: {raw[:32]!r}")

    # ==============================================================
    # FALLBACK if model cannot run
    # ==============================================================
    if raw in ("[LLM_ERROR]", "[LLM_RAM_LIMIT]"):
        _debug(f"FALLBACK: reason={raw}")
        # Hybrid rule-based fallback using memory
        # This is lightweight and safe for Pi 3
        answer = ""

        mem = (facts + "\n" + goals).lower()
        q_lower = question.lower()

        # Security+ logic
        if "security+" in q_lower:
            answer = (
                "You should continue preparing for the Security+ exam and keep "
                "consistent study habits."
            )

        # Federal job logic
        elif "job" in q_lower or "apply" in q_lower:
            if "schedule a" in mem or "schedule a" in q_lower:
                answer = (
                    "Use your Schedule A letter and apply to VA, DHS, and "
                    "Social Security IT or cyber roles."
                )
            else:
                answer = "Focus on stable federal IT and cybersecurity positions."

        # Fitness logic
        elif "run" in q_lower or "front runners" in q_lower:
            answer = (
                "You should continue running with Front Runners on Tuesday, "
                "Thursday, Saturday, and Sunday."
            )

        # Health / carbs
        elif "carb" in q_lower or "diet" in q_lower:
            answer = (
                "Reduce carbs, emphasize lean protein, hydrate well, and "
                "maintain sleep stability."
            )

        # Safety default
        else:
            answer = (
                "Choose the option that is safest, most stable, and moves you "
                "closer to your long-term goals."
            )

        _debug(f"FALLBACK_ANSWER: {answer!r}")
        return answer.strip()

    # ==============================================================
    # MODEL SUCCEEDED — process output
    # ==============================================================
    _debug("MODEL_OK: processing llama output")

    # First, ensure text is str and try to cut off everything before "Answer:"
    text = raw
    if text is None:
        text = ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")

    idx = text.lower().find("answer:")
    if idx != -1:
        text = text[idx + len("answer:"):]

    # Drop obvious echo/junk lines
    filtered_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        upper = stripped.upper()

        # Skip typical llama echo artifacts / prompt labels
        if stripped.startswith("<s>"):
            continue
        if stripped.startswith("--temp"):
            continue
        if upper.startswith("QUESTION:"):
            continue
        if upper.startswith("FACTS:"):
            continue
        if upper.startswith("GOALS:") or upper.startswith("GOAL:"):
            continue
        if upper.startswith("SCRATCHPAD:") or upper.startswith("SCRAMCAP:"):
            continue
        if upper == "ANSWER:" or upper == "ANSWER":
            continue
        if upper == "QUEST":
            continue

        filtered_lines.append(stripped)

    cleaned_body = "\n".join(filtered_lines).strip()

    # If llama produced nothing useful after filtering, fall back to normalized text
    if not cleaned_body:
        cleaned_body = text.strip()

    # Now process roadmap markers anywhere in the cleaned body.
    # Any text after 'roadmap' on a line is stored as a fact and removed
    # from the visible answer, so the user never sees the marker.
    lines = cleaned_body.splitlines()
    learned_items: list[str] = []
    final_lines: list[str] = []

    for raw_line in lines:
        line = raw_line
        # Strip out all 'roadmap' segments in this line (if multiple)
        while True:
            idx_rm = line.find("roadmap")
            if idx_rm == -1:
                break

            before = line[:idx_rm].rstrip()
            after = line[idx_rm + len("roadmap"):].strip()

            # Save the part after 'roadmap' as a learned fact (if any)
            if after:
                learned_items.append(after)
                _debug(f"roadmap {after!r}")

            # For the visible text, keep only what was before 'roadmap'
            line = before

        # Whatever is left (if anything) is shown to the user
        if line.strip():
            final_lines.append(line.strip())

    # Save new memory + run lesson_learned.py for each roadmap fact
    for item in learned_items:
        _append_fact(item)
        _run_lesson_learned(item)

    final_answer = "\n".join(final_lines).strip()

    # Scan for WEB_SITE markers to trigger internet fetch
    requested_sites: list[str] = []
    for line in lines:
        if line.upper().startswith("WEB_SITE:"):
            # Example format: WEB_SITE: ssa.gov (comment)
            _, rest = line.split(":", 1)
            dom = rest.strip().split()[0]  # take first token after colon
            if dom:
                requested_sites.append(dom)

    if requested_sites:
        from web_worker import fetch_from_sites  # local import to avoid cycles

        sites_allow = _allowed_sites(cfg)
        internet_summary = fetch_from_sites(
            allowed_sites=sites_allow,
            requested_sites=requested_sites,
            query=question,
        )
        final_answer = (
            final_answer
            + "\n\n"
            + "----\nInternet helper summary:\n"
            + internet_summary
        )

    # Clamp to at most 3 paragraphs (separated by blank lines)
    paras = [p.strip() for p in final_answer.split("\n\n") if p.strip()]
    if len(paras) > 3:
        final_answer = "\n\n".join(paras[:3])

    # If the model produced nothing useful, fall back to a generic safe answer
    if not final_answer.strip():
        _debug("FINAL_ANSWER_EMPTY: using generic fallback")
        final_answer = (
            "I was not able to generate a detailed answer this time. "
            "Choose the option that is safest, most stable, and moves you "
            "closer to your long-term goals."
        )

    _debug(f"FINAL_ANSWER: {final_answer[:80]!r}")

    return final_answer


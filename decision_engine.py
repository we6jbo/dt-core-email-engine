"""
decision_engine.py
Real AI interface for Raspberry Pi (hybrid rules + tiny llama.cpp model).

- Reads memory from /var/lib/dt-core-database/
- Attempts to use llama.cpp tiny model
- Falls back to memory-based reasoning if RAM is too low or model fails
- Writes new memory automatically
- Runs lesson_learned.py when new facts are discovered
"""

import os
import json
import subprocess
from pathlib import Path
from models import DTRequest

# ===== PATHS ===============================================================

DB = Path("/var/lib/dt-core-database/")
FACTS = DB / "facts.txt"
GOALS = DB / "goals.txt"
SCRATCH = DB / "scratchpad.json"

# model.bin is a symlink to tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
MODEL = DB / "model.bin"
LLAMA = "/usr/local/bin/llama"     # installed by install_local_ai.sh

DEBUG_LOG = DB / "decision_engine_debug.log"

# ===== DEBUG HELPER ========================================================

def _debug(msg: str) -> None:
    """Best-effort append-only debug logging."""
    try:
        DB.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        # Never let logging crash the engine
        pass

# ===== HELPERS =============================================================

def _safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _append_fact(text: str) -> None:
    DB.mkdir(parents=True, exist_ok=True)
    with FACTS.open("a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def _run_lesson_learned(text: str) -> None:
    """Run lesson_learned.py by passing text through stdin."""
    try:
        subprocess.run(
            ["python3", "/var/lib/dt-core/lesson_learned.py"],
            input=text.encode("utf-8"),
            timeout=20
        )
    except Exception:
        # Never crash the engine on lesson_learned errors
        pass


def _ram_too_low() -> bool:
    """Return True if RAM is likely too low for tiny llama."""
    # Allow override for testing:
    #   DT_IGNORE_RAM_CHECK=1 python3 ...
    if os.environ.get("DT_IGNORE_RAM_CHECK") == "1":
        return False

    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.strip().split()[0])

        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", 0)

        # Loosened thresholds for Pi 3:
        # - total < ~0.7GB → too small for comfort
        # - available < ~250MB → likely to OOM if we run llama
        if total < 700_000:      # < ~0.7 GB
            return True
        if free < 250_000:       # < ~250 MB available
            return True
    except Exception:
        # If we can't read meminfo safely, be conservative
        return True

    return False


def _run_llama(prompt: str) -> str:
    """
    Run llama.cpp safely. Returns '[LLM_ERROR]' on failure.

    Tuned for Raspberry Pi 3:
    - Very small n_predict to keep runtime reasonable.
    - Generous timeout so the model can actually finish.
    """
    if not MODEL.exists() or not os.path.exists(LLAMA):
        _debug("LLM: MODEL or LLAMA missing → [LLM_ERROR]")
        return "[LLM_ERROR]"

    if _ram_too_low():
        _debug("LLM: _ram_too_low() → [LLM_RAM_LIMIT]")
        return "[LLM_RAM_LIMIT]"

    try:
        _debug("LLM: starting llama subprocess")
        result = subprocess.run(
            [
                LLAMA,
                "-m", str(MODEL),
                "-n", "24",          # keep it short for Pi 3
                "--temp", "0.5",
                prompt,              # positional prompt (no -p flag)
            ],
            capture_output=True,
            text=True,
            timeout=180             # plenty of time for slow hardware
        )
        out = (result.stdout or "").strip()
        _debug(f"LLM: returncode={result.returncode}, len(stdout)={len(out)}")
        if not out:
            _debug("LLM: empty stdout → [LLM_ERROR]")
            return "[LLM_ERROR]"
        return out
    except Exception as e:
        _debug(f"LLM: exception → [LLM_ERROR]: {repr(e)}")
        return "[LLM_ERROR]"


# ===== MAIN AI LOGIC ======================================================

def generate_answer(request: DTRequest) -> str:
    question = (request.question or "respond with CIAARQE").strip()

    # Identify which file ran, once per call
    _debug("")
    _debug(f"=== generate_answer called in {__file__} ===")
    _debug(f"QUESTION: {question!r}")

    facts = _safe_read(FACTS)
    goals = _safe_read(GOALS)
    scratch = _safe_read(SCRATCH)

    # Prompt for model
    # Prompt for model – short and causal, ends with 'Answer:'
    prompt = (
        f"QUESTION:\n{question}\n\n"
    )

    raw = _run_llama(prompt)
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
            answer = "You should continue preparing for the Security+ exam and keep consistent study habits."

        # Federal job logic
        elif "job" in q_lower or "apply" in q_lower:
            if "schedule a" in mem or "schedule a" in q_lower:
                answer = "Use your Schedule A letter and apply to VA, DHS, and Social Security IT or cyber roles."
            else:
                answer = "Focus on stable federal IT and cybersecurity positions."

        # Fitness logic
        elif "run" in q_lower or "front runners" in q_lower:
            answer = "You should continue running with Front Runners on Tuesday, Thursday, Saturday, and Sunday."

        # Health / carbs
        elif "carb" in q_lower or "diet" in q_lower:
            answer = "Reduce carbs, emphasize lean protein, hydrate well, and maintain sleep stability."

        # Safety default
        else:
            answer = "Choose the option that is safest, most stable, and moves you closer to your long-term goals."

        _debug(f"FALLBACK_ANSWER: {answer!r}")
        return answer.strip()

    # ==============================================================
    # MODEL SUCCEEDED — process output
    # ==============================================================
    _debug("MODEL_OK: processing llama output")
    lines = raw.splitlines()
    learned = None
    for line in lines:
        if line.startswith("NEW_FACT:"):
            learned = line.replace("NEW_FACT:", "").strip()

    # Save new memory + run lesson_learned.py
    if learned:
        _debug(f"NEW_FACT: {learned!r}")
        _append_fact(learned)
        _run_lesson_learned(learned)

    # Remove NEW_FACT lines
    cleaned = "\n".join([l for l in lines if not l.startswith("NEW_FACT:")]).strip()
    _debug(f"FINAL_ANSWER: {cleaned[:80]!r}")

    return cleaned


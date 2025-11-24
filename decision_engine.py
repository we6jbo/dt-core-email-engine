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

MODEL = DB / "model.bin"
LLAMA = "/usr/local/bin/llama"     # installed by install_local_ai.sh

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
        pass


def _ram_too_low() -> bool:
    """Return True if RAM < 1GB or system is under pressure."""
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.strip().split()[0])

        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", 0)

        # Pi 3 has ~945 MB total; llama.cpp often needs 600–800 MB available.
        if total < 900000:          # < ~0.9GB
            return True
        if free < 500000:           # < ~500MB available RAM
            return True
    except Exception:
        return True

    return False


def _run_llama(prompt: str) -> str:
    """Run llama.cpp safely. Returns '[LLM_ERROR]' on failure."""
    if not MODEL.exists() or not os.path.exists(LLAMA):
        return "[LLM_ERROR]"

    if _ram_too_low():
        return "[LLM_RAM_LIMIT]"

    try:
        result = subprocess.run(
            [LLAMA, "-m", str(MODEL), "-p", prompt, "-n", "200", "--temp", "0.5"],
            capture_output=True,
            text=True,
            timeout=65
        )
        out = result.stdout.strip()
        if not out:
            return "[LLM_ERROR]"
        return out
    except Exception:
        return "[LLM_ERROR]"


# ===== MAIN AI LOGIC ======================================================

def generate_answer(request: DTRequest) -> str:
    question = (request.question or "").strip()

    facts = _safe_read(FACTS)
    goals = _safe_read(GOALS)
    scratch = _safe_read(SCRATCH)

    # Prompt for model
    prompt = f"""
You are a tiny offline AI running on a Raspberry Pi 3.
Use the memory below to choose the *best decision*.

FACTS:
{facts}

GOALS:
{goals}

SCRATCHPAD:
{scratch}

QUESTION:
{question}

RULES:
- Output ONLY the final answer in 1–3 sentences.
- If you learn a new stable fact, write: NEW_FACT:<text>
- Do not include headings or formatting.
"""

    raw = _run_llama(prompt)

    # ==============================================================
    # FALLBACK if model cannot run
    # ==============================================================
    if raw in ("[LLM_ERROR]", "[LLM_RAM_LIMIT]"):
        # Hybrid rule-based fallback using memory
        # This is lightweight and safe for Pi 3
        answer = ""

        mem = (facts + "\n" + goals).lower()

        # Security+ logic
        if "security+" in question.lower():
            answer = "You should continue preparing for the Security+ exam and keep consistent study habits."

        # Federal job logic
        elif "job" in question.lower() or "apply" in question.lower():
            if "schedule a" in mem or "schedule a" in question.lower():
                answer = "Use your Schedule A letter and apply to VA, DHS, and Social Security IT or cyber roles."
            else:
                answer = "Focus on stable federal IT and cybersecurity positions."

        # Fitness logic
        elif "run" in question.lower() or "front runners" in question.lower():
            answer = "You should continue running with Front Runners on Tuesday, Thursday, Saturday, and Sunday."

        # Health / carbs
        elif "carb" in question.lower() or "diet" in question.lower():
            answer = "Reduce carbs, emphasize lean protein, hydrate well, and maintain sleep stability."

        # Safety default
        else:
            answer = "Choose the option that is safest, most stable, and moves you closer to your long-term goals."

        return answer.strip()

    # ==============================================================
    # MODEL SUCCEEDED — process output
    # ==============================================================
    lines = raw.splitlines()
    learned = None
    for line in lines:
        if line.startswith("NEW_FACT:"):
            learned = line.replace("NEW_FACT:", "").strip()

    # Save new memory + run lesson_learned.py
    if learned:
        _append_fact(learned)
        _run_lesson_learned(learned)

    # Remove NEW_FACT lines
    cleaned = "\n".join([l for l in lines if not l.startswith("NEW_FACT:")]).strip()

    return cleaned


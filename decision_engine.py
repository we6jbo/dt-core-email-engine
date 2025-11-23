"""
decision_engine: placeholder AI / decision-tree logic.

Right now this is deliberately simple so you can swap in a real AI later.
"""

from models import DTRequest


def generate_answer(request: DTRequest) -> str:
    """
    Very small "AI-like" engine.

    It looks at the question text and tries to choose a best option in a
    decision-tree style way, but it mostly just echoes the question and adds
    structure so you can later plug in a real model.
    """
    q = (request.question or "").strip().lower()

    if not q:
        decision = (
            "I did not see a clear question, so the safest option is to do "
            "nothing and ask for clarification."
        )
    elif any(keyword in q for keyword in ["yes or no", "y/n", "should i"]):
        decision = "I recommend choosing the safest and most reversible option, then testing it with a small step."
    elif "test" in q and "working" in q:
        decision = (
            "The best option is to confirm that the round-trip email path works, "
            "then record that this request succeeded."
        )
    else:
        decision = (
            "Based on your question I would choose a cautious, incremental option. "
            "Start with the smallest change that lets you gather more information, "
            "then adjust from there."
        )

    return (
        "=== Decision Tree Core (placeholder AI) ===\n\n"
        f"Request-ID: {request.request_id}\n\n"
        f"Original question:\n{request.question}\n\n"
        "Suggested best option:\n"
        f"{decision}\n\n"
        "Note: This answer is coming from a simple rule-based engine. "
        "You can replace this function with a real AI model on or after 2025-11-23."
    )


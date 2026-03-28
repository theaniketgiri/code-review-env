from dataclasses import dataclass

try:
    from ..models import ISSUE_TAXONOMY
except ImportError:
    from models import ISSUE_TAXONOMY


@dataclass(frozen=True)
class Task:
    task_id: str
    difficulty: str
    description: str
    file_name: str
    code: str
    planted_issues: list[str]


TASKS: dict[str, Task] = {
    "task_easy": Task(
        task_id="task_easy",
        difficulty="easy",
        description=(
            "Review this Python function and identify issues using only taxonomy tags. "
            f"Allowed tags: {', '.join(ISSUE_TAXONOMY)}."
        ),
        file_name="user_service.py",
        code=(
            "def get_user_age(user):\n"
            "    # Returns age in years from user profile dict\n"
            "    birthdate = user.get(\"birthdate\")\n"
            "    if user.get(\"is_active\"):\n"
            "        account_label = f\"active:{user.get('id')}\"\n"
            "    else:\n"
            "        account_label = \"inactive\"\n"
            "\n"
            "    age = (datetime.now() - birthdate).days // 365\n"
            "    profile = {\"label\": account_label, \"age\": age}\n"
            "    # TODO: return something\n"
        ),
        planted_issues=["null_pointer", "missing_return"],
    ),
    "task_medium": Task(
        task_id="task_medium",
        difficulty="medium",
        description=(
            "Review this authentication module and return security-relevant tags from the taxonomy only. "
            f"Allowed tags: {', '.join(ISSUE_TAXONOMY)}."
        ),
        file_name="auth.py",
        code=(
            "SECRET_KEY = \"supersecret123\"   # used for JWT signing\n"
            "\n"
            "def authenticate_user(db_conn, username, password):\n"
            "    query = f\"SELECT * FROM users WHERE username='{username}' AND password='{password}'\"\n"
            "    result = db_conn.execute(query)\n"
            "    user = result.fetchone()\n"
            "\n"
            "    if user:\n"
            "        audit_line = f\"auth ok for {username}\"\n"
            "        token = jwt.encode({\"user_id\": user.id}, SECRET_KEY)\n"
            "        return token\n"
        ),
        planted_issues=["sql_injection", "hardcoded_secret"],
    ),
    "task_hard": Task(
        task_id="task_hard",
        difficulty="hard",
        description=(
            "Review this payment processing code for subtle concurrency, error-handling, and security flaws. "
            f"Use only taxonomy tags: {', '.join(ISSUE_TAXONOMY)}."
        ),
        file_name="payments.py",
        code=(
            "def process_payment(user_id, amount, card_token):\n"
            "    user = db.get_user(user_id)\n"
            "    if user.balance >= amount:\n"
            "        user.balance -= amount    # checked and modified non-atomically\n"
            "        db.save_user(user)\n"
            "\n"
            "        try:\n"
            "            charge_result = payment_gateway.charge(card_token, amount)\n"
            "        except:\n"
            "            pass  # silently swallow all payment errors\n"
            "\n"
            "        expected = db.get_token_hash(card_token)\n"
            "        actual = hash(card_token)\n"
            "        if expected == actual:    # non-constant-time comparison\n"
            "            return {\"status\": \"success\", \"charge\": charge_result}\n"
        ),
        planted_issues=["race_condition", "improper_error_handling", "timing_attack"],
    ),
}


def get_task(task_id: str) -> Task:
    """Return task by id, defaulting to task_easy for unknown ids."""
    return TASKS.get(task_id, TASKS["task_easy"])

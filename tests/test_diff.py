from agenttrace import diff
from agenttrace.model import Trace


def _trace_with_user_input(u):
    return Trace(run_id="r", agent="codex",
                 seed={"system_prompt": None, "user_input": u},
                 turns=[], incomplete=False)


def test_diff_marks_changed_prompt_lines():
    a = _trace_with_user_input("find the bug\nbe careful")
    b = _trace_with_user_input("find the bug\nbe very careful")
    html = diff(a, b)
    assert "be careful" in html and "be very careful" in html
    assert 'class="diff-add"' in html and 'class="diff-del"' in html

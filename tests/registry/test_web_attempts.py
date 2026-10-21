"""Tier1: the teacher's matrix (not run / in progress / passed) and the history with outputs."""
import pytest

from hashpass.registry.web import render_dashboard, render_history

PROFILES = [{"user": "s1", "role": "student", "group": "G", "comment": ""}]
ENTRIES = [{"number": 1, "ref": "lab:1"}, {"number": 2, "ref": "lab:2"},
           {"number": 3, "ref": "lab:3"}]


def _cells(html: str) -> list[str]:
    row = html[html.index("<td class='mono'><a href='/web/user/s1'>s1</a></td>"):]
    row = row[:row.index("</tr>")]
    return [m for m in ("·", "◐", "✓") for _ in range(row.count(m))]


@pytest.mark.tier1
def test_matrix_three_states():
    attempts = {"s1": {"lab:2": {"sessions": 2, "passed": False, "live": True},
                       "lab:3": {"sessions": 1, "passed": True, "live": False}}}
    html = render_dashboard(PROFILES, ENTRIES, {}, attempts=attempts)
    assert sorted(_cells(html)) == sorted(["·", "◐", "✓"])
    assert "сейчас решает" in html                       # the live cell says so on hover
    assert "/web/history?user=s1&amp;ref=lab%3A2" in html or "/web/history?user=s1&ref=lab%3A2" in html


def _session(sid: str, final: str | None, started: float, cmds: list[tuple[str, str]]) -> dict:
    return {"session_id": sid, "ref": "lab:1", "started": started, "updated": started + 90,
            "final": final, "truncated": False,
            "entries": [{"command": c, "output": o, "ts": "t", "typing": 3.0, "pasted": False}
                        for c, o in cmds]}


@pytest.mark.tier1
def test_history_solution_and_attempts_with_output():
    sessions = [_session("b" * 32, "passed", 200.0, [("ls -l", "total 0\n")]),
                _session("a" * 32, "abandoned", 100.0, [("lss", "bash: lss: command not found\n")])]
    html = render_history("s1", "lab:1", {"status": "passed"}, sessions=sessions, now=10_000.0)
    assert "✓ решение" in html
    assert html.index("ls -l") < html.index("<details")      # the solution comes first, open
    assert "total 0" in html
    assert "bash: lss: command not found" in html            # failed attempts keep their output
    assert "вышел" in html
    assert "http-equiv='refresh'" not in html


@pytest.mark.tier1
def test_history_live_session_refreshes_and_escapes():
    sessions = [_session("c" * 32, None, 1000.0, [("echo '</pre><script>x</script>'",
                                                   "</pre><script>x</script>\n")])]
    html = render_history("s1", "lab:1", {}, sessions=sessions, now=1100.0)
    assert "сейчас решает" in html
    assert "http-equiv='refresh'" not in html           # live: polled in place, no page reload
    assert "data-live-src='/web/history/live?user=s1&ref=lab%3A1'" in html
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.tier1
def test_history_old_record_without_sessions():
    rec = {"status": "passed", "history": [{"command": "chmod +x a", "typing": 2.0}]}
    html = render_history("s1", "lab:1", rec, sessions=[])
    assert "chmod +x a" in html
    assert "<details" not in html


@pytest.mark.tier1
def test_history_shows_every_attempt_open_and_marks_empty_output():
    sessions = [_session("b" * 32, "abandoned", 200.0, [("true", "")]),
                _session("a" * 32, "abandoned", 100.0, [("lss", "bash: lss\n")])]
    html = render_history("s1", "lab:1", {}, sessions=sessions, now=10_000.0)
    assert html.count("<details") == html.count("<details class='session' open")   # all open
    assert "нет вывода" in html
    assert "id='s-" + "b" * 32 + "'" in html                  # stable ids keep the state on refresh


@pytest.mark.tier1
def test_history_fragment_and_signature_change_with_new_commands():
    from hashpass.registry.web import render_history_live  # noqa: PLC0415
    one = [_session("c" * 32, None, 1000.0, [("ls", "a\n")])]
    two = [_session("c" * 32, None, 1000.0, [("ls", "a\n"), ("pwd", "/home\n")])]
    _, sig1 = render_history_live("s1", "lab:1", {}, sessions=one, now=1100.0)
    frag2, sig2 = render_history_live("s1", "lab:1", {}, sessions=two, now=1100.0)
    assert sig1 != sig2
    assert "<html" not in frag2 and "/home" in frag2 and "pwd" in frag2

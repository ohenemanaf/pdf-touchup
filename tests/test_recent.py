from datetime import datetime, timedelta

from pdf_touchup.ui.recent import RecentFiles, relative_day


def _touch(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4")
    return p


def test_recent_keeps_newest_first_max_8(settings, tmp_path):
    recent = RecentFiles(settings)
    for i in range(10):
        recent.add(_touch(tmp_path, f"f{i}.pdf"), "Typed")
    names = [r.path.name for r in recent.items()]
    assert names == [f"f{i}.pdf" for i in range(9, 1, -1)]


def test_recent_moves_reopened_file_to_top(settings, tmp_path):
    recent = RecentFiles(settings)
    a, b = _touch(tmp_path, "a.pdf"), _touch(tmp_path, "b.pdf")
    recent.add(a, "Typed")
    recent.add(b, "Scanned")
    recent.add(a, "Typed")
    assert [r.path.name for r in recent.items()] == ["a.pdf", "b.pdf"]
    assert RecentFiles(settings).items()[1].kind == "Scanned"  # persisted


def test_recent_drops_missing_files(settings, tmp_path):
    recent = RecentFiles(settings)
    gone = _touch(tmp_path, "gone.pdf")
    recent.add(gone, "Typed")
    recent.add(_touch(tmp_path, "here.pdf"), "Typed")
    gone.unlink()
    assert [r.path.name for r in recent.items()] == ["here.pdf"]


def test_relative_day():
    now = datetime(2026, 11, 14, 15, 0)
    assert relative_day(now - timedelta(hours=2), now) == "today"
    assert relative_day(now - timedelta(days=1), now) == "yesterday"
    assert relative_day(now - timedelta(days=3), now) == "3 days ago"
    assert relative_day(datetime(2026, 3, 12, 9, 0), now) == "12 Mar"

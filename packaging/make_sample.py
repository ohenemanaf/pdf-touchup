"""Writes a small scanned-style sample PDF used by the build's --self-test step."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from conftest import make_native, make_scanned  # noqa: E402

out = Path(sys.argv[1]).resolve()
out.parent.mkdir(parents=True, exist_ok=True)
make_scanned(out, make_native(out.with_name("sample-native.pdf")))
print(out)

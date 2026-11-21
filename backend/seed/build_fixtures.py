"""Generates the two synthetic DOCX fixtures with the application's own resume builder.

Run once from backend/:  python -m seed.build_fixtures
The output files are committed. Tests check the committed files; they do not regenerate them, because a DOCX carries
its own package metadata and a fresh build is not byte-identical. Their text is what the tests compare.
"""
from pathlib import Path

from resume_builder import build_resume_bytes
from seed.synthetic_seed import FIXTURE_DIR, RESUME_A, RESUME_B


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "synthetic_resume_sam_example.docx").write_bytes(build_resume_bytes(RESUME_A, ats_mode=False, template="classic"))
    (FIXTURE_DIR / "synthetic_resume_riley_sample.docx").write_bytes(build_resume_bytes(RESUME_B, ats_mode=False, template="modern"))
    for name in ("synthetic_resume_sam_example.docx", "synthetic_resume_riley_sample.docx"):
        print(Path(FIXTURE_DIR / name).name, (FIXTURE_DIR / name).stat().st_size, "bytes")


if __name__ == "__main__":
    main()

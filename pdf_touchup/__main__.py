import multiprocessing
import sys


def _entry() -> None:
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from pdf_touchup.selftest import run

        sys.exit(run(sys.argv[2]))
    from pdf_touchup.ui.app import main

    main()


if __name__ == "__main__":
    _entry()

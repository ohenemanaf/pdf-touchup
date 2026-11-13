import multiprocessing

from pdf_touchup.ui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

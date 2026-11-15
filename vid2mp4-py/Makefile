# vid2mp4: build from source. Needs Python 3.10+, and ffmpeg + ffprobe on PATH to run.
#
#   make install    install dependencies
#   make exe        build dist/vid2mp4.exe (command line) and dist/vid2mp4-gui.exe (window)
#   make clean      remove build artifacts

PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help install exe exe-cli exe-gui clean

help:
	@echo "vid2mp4 - video to MP4 converter"
	@echo "  make install   install dependencies"
	@echo "  make exe       build dist/vid2mp4.exe (command line) and dist/vid2mp4-gui.exe (window)"
	@echo "  make clean     remove build artifacts"

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

exe: install exe-cli exe-gui

exe-cli:
	$(PYTHON) -m PyInstaller --onefile --console --exclude-module tkinter --collect-submodules rich --name vid2mp4 --add-data "VERSION:." --clean vid2mp4.py

exe-gui:
	$(PYTHON) -m PyInstaller --onefile --windowed --exclude-module rich --collect-all tkinterdnd2 --name vid2mp4-gui --add-data "VERSION:." --clean vid2mp4_gui.py

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(d, ignore_errors=True) for d in ('build', 'dist', '__pycache__')]; [f.unlink() for f in pathlib.Path('.').glob('*.spec')]"

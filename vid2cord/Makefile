# vid2cord: build from source. Needs Python 3.10+, and ffmpeg + ffprobe on PATH to run.
#
#   make install    install dependencies
#   make exe        build dist/vid2cord.exe
#   make clean      remove build artifacts

PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help install exe clean

help:
	@echo "vid2cord - Discord video re-encoder"
	@echo "  make install   install dependencies"
	@echo "  make exe       build dist/vid2cord.exe"
	@echo "  make clean     remove build artifacts"

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

exe: install
	$(PYTHON) -m PyInstaller --onefile --console --name vid2cord --add-data "VERSION:." --clean vid2cord.py

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(d, ignore_errors=True) for d in ('build', 'dist', '__pycache__')]; [f.unlink() for f in pathlib.Path('.').glob('*.spec')]"

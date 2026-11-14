# png2jpg: build from source. Needs Python 3.10+.
#
#   make install    install dependencies
#   make exe        build dist/png2jpg.exe
#   make clean      remove build artifacts

PYTHON ?= python

.DEFAULT_GOAL := help
.PHONY: help install exe clean

help:
	@echo "png2jpg - PNG to JPG converter"
	@echo "  make install   install dependencies"
	@echo "  make exe       build dist/png2jpg.exe"
	@echo "  make clean     remove build artifacts"

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

exe: install
	$(PYTHON) -m PyInstaller --onefile --console --name png2jpg --add-data "VERSION:." --clean png2jpg.py

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(d, ignore_errors=True) for d in ('build', 'dist', '__pycache__')]; [f.unlink() for f in pathlib.Path('.').glob('*.spec')]"

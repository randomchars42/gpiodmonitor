.PHONY: run setup build upload

run:
	pipenv run gpiodmonitor

setup:
	pipenv install --dev

build:
	rm -rf dist
	pipenv run python -m build

upload:
	pipenv run python -m twine upload dist/*

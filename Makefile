#!/usr/bin/make
PYTHON := /usr/bin/env python3

lint:
	@tox -e pep8

test:
	@echo Starting unit tests...
	@tox -e py3

functional_test:
	@echo Starting functional tests...
	@tox -e func

all: test lint

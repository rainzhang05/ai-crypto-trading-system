preflight:
	python3 -m compileall -q backend execution scripts tests
	pytest -q

test:
	./scripts/test_all.sh

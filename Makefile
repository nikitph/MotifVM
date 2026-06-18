.PHONY: test demo eval adversarial

test:
	python3 -m unittest discover -s tests
	python3 -m py_compile motifvm/*.py

demo:
	python3 -m motifvm.demo

eval:
	python3 -m motifvm.eval

adversarial:
	python3 -m motifvm.adversarial

.PHONY: test demo eval adversarial adversarial-100 adapter-conformance compiler-eval

test:
	python3 -m unittest discover -s tests
	python3 -m py_compile motifvm/*.py

demo:
	python3 -m motifvm.demo

eval:
	python3 -m motifvm.eval

adversarial:
	python3 -m motifvm.adversarial

adversarial-100:
	python3 -m motifvm.adversarial_100

adapter-conformance:
	python3 -m motifvm.adapter_conformance

compiler-eval:
	python3 -m motifvm.compiler_eval

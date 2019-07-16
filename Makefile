.PHONY	: all

all:
	python vcd2wavedrom.py --input example.vcd --config exampleconfig.json > tmp.drom && wavedrom-cli -i tmp.drom -s example.svg

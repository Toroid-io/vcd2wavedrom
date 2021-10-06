# vcd2wavedrom

Python script to transform a VCD file to [wavedrom](https://wavedrom.com/) format

```
usage: vcd2wavedrom.py [-h] [--config CONFIGFILE] --input [INPUT] [--output [OUTPUT]]

Transform VCD to wavedrom

optional arguments:
  -h, --help           show this help message and exit
  --config CONFIGFILE
  --input [INPUT]
  --output [OUTPUT]
```

## Quickstart

Test the example given by running `make` in the project directory.

## Auto configuration

If no configuration file is provided, a default configuration will be
created based on the contents of the vcd file.

## Config options

### Signal

The signal key is appended to the corresponding signal in the wavedrom
output. You can add here wavedrom parameters.

### Filter

You can select which signals are included in the wavedrom output by
adding the signal name to this list. The resulting list is created in
this order.

### Repalce

Raw values may be replaced by a more human readable text. See the
example config file for an example.

### Offset

This is the first tick from which sample the vcd waves.

### Samplerate

Should be set to clock period / resolution of simulation.

### Clocks

List of clock signals (high level is replaced by clock edge symbol.

### Maxtime

Sample (or extend last value) until `maxtime`.

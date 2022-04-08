#!/usr/bin/env python

import sys
import os
import argparse
import json
import re

# from Verilog_VCD import parse_vcd
# from Verilog_VCD import get_timescale
from vcdvcd.vcdvcd import VCDVCD

from math import floor, ceil

class VCD2Wavedrom:

    busregex = re.compile(r'(.+)(\[|\()(\d+)(\]|\))')
    busregex2 = re.compile(r'(.+)\[(\d):(\d)\]')
    config = {}
    bit_open = None
    bit_close = None

    def __init__(self, config):
        self.config = config

    def replacevalue(self, wave, strval):
        if 'replace' in self.config and \
        wave in self.config['replace']:
            if strval in self.config['replace'][wave]:
                return self.config['replace'][wave][strval]
        return strval

    def group_buses(self, vcd_dict, slots):
        buses = {}
        buswidth = {}
        global bit_open
        global bit_close

        """
        Extract bus name and width
        """
        for isig, wave in enumerate(vcd_dict):
            result = self.busregex.match(wave)
            if result is not None and len(result.groups()) == 4:
                name = result.group(1)
                pos = int(result.group(3))
                self.bit_open = result.group(2)
                self.bit_close = ']' if self.bit_open == '[' else ')'
                if name not in buses:
                    buses[name] = {
                            'name': name,
                            'wave': '',
                            'data': []
                    }
                    buswidth[name] = 0
                if pos > buswidth[name]:
                    buswidth[name] = pos

        """
        Create hex from bits
        """
        for wave in buses:
            for slot in range(slots):
                if not self.samplenow(slot):
                    continue
                byte = 0
                strval = ''
                for bit in range(buswidth[wave]+1):
                    if bit % 8 == 0 and bit != 0:
                        strval = format(byte, 'X')+strval
                        byte = 0
                    val = vcd_dict[wave+self.bit_open+str(bit)+self.bit_close][slot][1]
                    if val != '0' and val != '1':
                        byte = -1
                        break
                    byte += pow(2, bit % 8) * int(val)
                strval = format(byte, 'X')+strval
                if byte == -1:
                    buses[wave]['wave'] += 'x'
                else:
                    strval = self.replacevalue(wave, strval)
                    if len(buses[wave]['data']) > 0 and \
                        buses[wave]['data'][-1] == strval:
                        buses[wave]['wave'] += '.'
                    else:
                        buses[wave]['wave'] += '='
                        buses[wave]['data'].append(strval)
        return buses

    def auto_config_waves(self, vcd_dict):
        startTime = -1
        syncTime = -1
        endTime = -1
        minDiffTime = -1

        """
        Warning: will overwrite all information from config file if any
        Works best with full synchronous signals
        """

        self.config['filter'] = ['__all__']
        self.config['clocks'] = []
        self.config['signal'] = []

        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            if len(wave_points) == 0:
                raise ValueError(f"Signal {wave} is empty!")
            wave_first_point = wave_points[0]
            wave_first_time = wave_first_point[0]
            if (startTime < 0) or (wave_first_time < startTime):
                startTime = wave_first_time

            if (len(wave_points) > 1) and ((syncTime < 0) or (wave_points[1][0] < syncTime)):
                syncTime = wave_points[1][0]

            for wave_point in wave_points:
                if (endTime < 0) or (wave_point[0] > endTime):
                    endTime = wave_point[0]

            for tidx in range(2, len(wave_points)):
                tmpDiff = wave_points[tidx][0] - wave_points[tidx - 1][0]
                if (wave_points[tidx - 1][0] >= startTime):
                    if ((minDiffTime < 0) or (tmpDiff < minDiffTime)) and (tmpDiff > 0):
                        minDiffTime = tmpDiff

        # Corner case
        if minDiffTime < 0:
            for tidx in range(1, len(wave_points)):
                tmpDiff = wave_points[tidx][0] - wave_points[tidx - 1][0]
                if (wave_points[tidx - 1][0] >= startTime):
                    if ((minDiffTime < 0) or (tmpDiff < minDiffTime)) and (tmpDiff > 0):
                        minDiffTime = tmpDiff

        # 1st loop to refine minDiffTime for async design or multiple async clocks
        tmpRatio = 1
        tmpReal = 0
        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            for wave_point in wave_points:
                tmpReal = (wave_point[0] - syncTime) / minDiffTime / tmpRatio
                if abs(tmpReal - round(tmpReal)) > 0.25:
                    # not too much otherwise un-readable
                    if tmpRatio < 4:
                        tmpRatio = tmpRatio * 2

        minDiffTime = minDiffTime / tmpRatio
        startTime = syncTime - \
            ceil((syncTime - startTime) / minDiffTime) * minDiffTime

        # 2nd loop to apply rounding
        tmpReal = 0
        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            for wave_point in wave_points:
                tmpReal = (wave_point[0] - startTime) / minDiffTime
                wave_point[0] = round(tmpReal)
            wave_points[0][0] = 0

        if 'maxtime' in self.config and self.config['maxtime'] is not None:
            self.config['maxtime'] = min(
                ceil((endTime - startTime) / minDiffTime), self.config['maxtime'])
        else:
            self.config['maxtime'] = ceil((endTime - startTime) / minDiffTime)

        return 1

    def homogenize_waves(self, vcd_dict, timescale):
        slots = int(self.config['maxtime']/timescale) + 1
        for isig, wave in enumerate(vcd_dict):
            lastval = 'x'
            for tidx, t in enumerate(range(0, self.config['maxtime'] + timescale, timescale)):
                if len(vcd_dict[wave]) > tidx:
                    newtime = vcd_dict[wave][tidx][0]
                else:
                    newtime = t + 1
                if newtime != t:
                    for ito_padd, padd in enumerate(range(t, newtime, timescale)):
                        vcd_dict[wave].insert(tidx+ito_padd, (padd, lastval))
                else:
                    lastval = vcd_dict[wave][tidx][1]
            vcd_dict[wave] = vcd_dict[wave][0:slots]


    def includewave(self, wave):
        if '__top__' in self.config['filter'] or ('top' in self.config and self.config['top']):
            return wave.count('.') <= 1
        elif '__all__' in self.config['filter'] or wave in self.config['filter']:
            return True
        return False


    def clockvalue(self, wave, digit):
        if wave in self.config['clocks'] and digit == '1':
            return 'P'
        return digit


    def samplenow(self, tick):
        offset = 0
        if 'offset' in self.config:
            offset = self.config['offset']

        samplerate = 1
        if 'samplerate' in self.config:
            samplerate = self.config['samplerate']

        if (tick - offset) >= 0 and (tick - offset) % samplerate <= 0:
            return True
        return False


    def appendconfig(self, wave):
        wavename = wave['name']
        if wavename in self.config['signal']:
            wave.update(self.config['signal'][wavename])

    def dump_wavedrom(self, vcd_dict, vcd_dict_types, timescale):
        drom = {'signal': [], 'config': {'hscale': 1}}
        slots = int(self.config['maxtime']/timescale)
        buses = self.group_buses(vcd_dict, slots)
        """
        Replace old signals that were grouped
        """
        for bus in buses:
            pattern = re.compile(r"^" + re.escape(bus) +
                                 "\\"+self.bit_open+".*")
            for wave in list(vcd_dict.keys()):
                if pattern.match(wave) is not None:
                    del vcd_dict[wave]
        """
        Create waveforms for the rest of the signals
        """
        idromsig = 0
        for wave in vcd_dict:
            if not self.includewave(wave):
                continue
            drom['signal'].append({
                'name': wave,
                'wave': '',
                'data': []
            })
            lastval = ''
            isbus = self.busregex2.match(
                wave) is not None or vcd_dict_types[wave] == 'bus'
            for j in vcd_dict[wave]:
                if not self.samplenow(j[0]):
                    continue
                digit = '.'
                value = None
                try:
                    value = int(j[1])
                    value = format(int(j[1], 2), 'X')
                except:
                    pass
                if value is None:
                    try:
                        value = float(j[1])
                        value = "{:.3e}".format(float(j[1]))
                    except:
                        pass
                if value is None:
                    value = j[1]
                if isbus or vcd_dict_types[wave] == 'string':
                    if lastval != j[1]:
                        digit = '='
                        if 'x' not in j[1]:
                            drom['signal'][idromsig]['data'].append(value)
                        else:
                            digit = 'x'
                else:
                    j = (j[0], self.clockvalue(wave, j[1]))
                    if lastval != j[1]:
                        digit = j[1]
                drom['signal'][idromsig]['wave'] += digit
                lastval = j[1]
            idromsig += 1

        """
        Insert buses waveforms
        """
        for bus in buses:
            if not self.includewave(bus):
                continue
            drom['signal'].append(buses[bus])

        """
        Order per config and add extra user parameters
        """
        ordered = []
        if '__all__' in self.config['filter']:
            ordered = drom['signal']
        else:
            for filtered in self.config['filter']:
                for wave in drom['signal']:
                    if wave['name'] == filtered:
                        ordered.append(wave)
                        self.appendconfig(wave)
        drom['signal'] = ordered
        if 'hscale' in self.config:
            drom['config']['hscale'] = self.config['hscale']

        return drom

    def execute(self, auto):
        vcd = VCDVCD(vcd_string=self.config['input_text'])
        timescale = int(vcd.timescale['magnitude'])
        vcd_dict = {}
        vcd_dict_types = {}
        vcd = vcd.data
        for i in vcd:
            if i != '$end':
                if int(vcd[i].size) > 1:
                    vcd_dict_types[vcd[i].references[0]] = 'bus'
                else:
                    vcd_dict_types[vcd[i].references[0]] = 'signal'
                vcd_dict[vcd[i].references[0]] = [list(tv) for tv in vcd[i].tv]

        if auto:
            timescale = self.auto_config_waves(vcd_dict)

        self.homogenize_waves(vcd_dict, timescale)
        return self.dump_wavedrom(vcd_dict, vcd_dict_types, timescale)


def main(argv):
    parser = argparse.ArgumentParser(description='Transform VCD to wavedrom')
    parser.add_argument('-i', '--input', dest='input', 
        help="Input VCD file", required=True)
    parser.add_argument('-o', '--output', dest='output', 
        help="Output Wavedrom file")
    parser.add_argument('-c', '--config', dest='configfile',
        help="Config file")
    parser.add_argument('-r', '--samplerate', dest='samplerate', type=int,
        help="Sample rate of wavedrom")
    parser.add_argument('-t', '--maxtime', dest='maxtime', type=int,
        help="Length of time for wavedrom")
    parser.add_argument('-f', '--offset', dest='offset', type=int,
        help="Time offset from start of VCD")
    parser.add_argument('-z', '--hscale', dest='hscale', type=int,
        help="Horizontal scale")
    parser.add_argument('--top', dest='top', action="store_true", default=False,
        help="Only output the top level signals")
    
    args = parser.parse_args(argv)
    args.input = os.path.abspath(os.path.join(os.getcwd(), args.input))

    config = {}

    if args.configfile:
        with open(args.configfile) as json_file:
            config.update(json.load(json_file))

    config['input'] = args.input
    try:
        with open(args.input, 'r') as f:
            config['input_text'] = f.read()
    except FileNotFoundError:
        print(f'ERROR: File {args.input} not found!')
        exit(1)

    config['output'] = args.output
    config['top'] = args.top
    if args.samplerate is not None:
        config['samplerate'] = args.samplerate
    if args.maxtime is not None:
        config['maxtime'] = args.maxtime 
    if args.offset is not None:
        config['offset'] = args.offset
    if args.hscale is not None:
        config['hscale'] = args.hscale

    vcd = VCD2Wavedrom(config)
    drom = vcd.execute(args.configfile is None)

    # Print the result
    if config['output'] is not None:
        f = open(config['output'], 'w')
        f.write(json.dumps(drom, indent=4))
    else:
        print(json.dumps(drom, indent=4))

if __name__ == '__main__':
    main(sys.argv[1:])

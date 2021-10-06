import sys
import os
import argparse
import json
import re

from Verilog_VCD import parse_vcd
from Verilog_VCD import get_timescale

from math import floor, ceil

busregex = re.compile(r'(.+)\[(\d+)\]')
busregex2 = re.compile(r'(.+)\[(\d):(\d)\]')
config = {}


def replacevalue(wave, strval):
    if 'replace' in config and \
       wave in config['replace']:
        if strval in config['replace'][wave]:
            return config['replace'][wave][strval]
    return strval


def group_buses(vcd_dict, slots):
    buses = {}
    buswidth = {}
    """
    Extract bus name and width
    """
    for isig, wave in enumerate(vcd_dict):
        result = busregex.match(wave)
        if result is not None and len(result.groups()) == 2:
            name = result.group(1)
            pos = int(result.group(2))
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
            if not samplenow(slot):
                continue
            byte = 0
            strval = ''
            for bit in range(buswidth[wave]+1):
                if bit % 8 == 0 and bit != 0:
                    strval = format(byte, 'X')+strval
                    byte = 0
                val = vcd_dict[wave+'['+str(bit)+']'][slot][1]
                if val != '0' and val != '1':
                    byte = -1
                    break
                byte += pow(2, bit % 8) * int(val)
            strval = format(byte, 'X')+strval
            if byte == -1:
                buses[wave]['wave'] += 'x'
            else:
                strval = replacevalue(wave, strval)
                if len(buses[wave]['data']) > 0 and \
                    buses[wave]['data'][-1] == strval:
                    buses[wave]['wave'] += '.'
                else:
                    buses[wave]['wave'] += '='
                    buses[wave]['data'].append(strval)
    return buses

def auto_config_waves(vcd_dict):
    startTime   = -1
    syncTime    = -1
    endTime     = -1
    minDiffTime = -1

    """
    Warning: will overwrite all information from config file if any
    Works best with full synchronous signals
    """

    config['filter'] = []
    config['clocks'] = []
    config['signal'] = []

    buses_widths = []

    for isig, wave in enumerate(vcd_dict):
        busresult = busregex.match(wave)
        if busresult is not None and len(busresult.groups()) == 2:
            name = busresult.group(1)
            if name not in config['filter']:
                config['filter'].append(name)
        else:
            config['filter'].append(wave)

        wave_points = vcd_dict[wave]
        wave_first_point = wave_points[0]
        wave_first_time = wave_first_point[0]
        if (startTime < 0) or (wave_first_time < startTime):
            startTime = wave_first_time

        if (len(wave_points) > 1) and ((syncTime < 0) or (wave_points[1][0] < syncTime)):
            syncTime = wave_points[1][0]

        bus_width = 1
        for wave_point in wave_points:
            if (endTime < 0) or (wave_point[0] > endTime):
                endTime = wave_point[0]
            if (len(wave_point[1]) > 1) and (len(wave_point[1]) > bus_width):
                bus_width = len(wave_point[1])
        buses_widths.append(bus_width)

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
    tmpReal  = 0
    for isig, wave in enumerate(vcd_dict):
        wave_points = vcd_dict[wave]
        for wave_point in wave_points:
            tmpReal = (wave_point[0] - syncTime) / minDiffTime / tmpRatio
            if abs(tmpReal - round(tmpReal)) > 0.25:
                # not too much otherwise un-readable
                if tmpRatio < 4:
                    tmpRatio = tmpRatio * 2

    minDiffTime = minDiffTime / tmpRatio
    startTime = syncTime - ceil((syncTime - startTime) / minDiffTime) * minDiffTime

    # 2nd loop to apply rounding
    tmpReal = 0
    for isig, wave in enumerate(vcd_dict):
        wave_points = vcd_dict[wave]
        for wave_point in wave_points:
            tmpReal = (wave_point[0] - startTime) / minDiffTime
            wave_point[0] = round(tmpReal)
            if tidx == 0:
                wave_point[0] = 0
            while len(wave_point[1]) < buses_widths[isig]:
                wave_point[1] = '0' + wave_point[1]

    config['maxtime'] = ceil((endTime - startTime) / minDiffTime)

    return 1

def homogenize_waves(vcd_dict, timescale):
    slots = int(config['maxtime']/timescale) + 1
    for isig, wave in enumerate(vcd_dict):
        lastval = 'x'
        for tidx, t in enumerate(range(0, config['maxtime'] + timescale, timescale)):
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


def includewave(wave):
    if '__all__' in config['filter'] or \
       wave in config['filter']:
        return True
    return False


def clockvalue(wave, digit):
    if wave in config['clocks'] and digit == '1':
        return 'P'
    return digit


def samplenow(tick):
    offset = 0
    if 'offset' in config:
        offset = config['offset']

    samplerate = 1
    if 'samplerate' in config:
        samplerate = config['samplerate']

    if ((tick - offset) % samplerate) == 0:
        return True
    return False


def appendconfig(wave):
    wavename = wave['name']
    if wavename in config['signal']:
        wave.update(config['signal'][wavename])


def dump_wavedrom(vcd_dict, timescale):
    drom = {'signal': [], 'config': {'hscale': 1}}
    slots = int(config['maxtime']/timescale)
    buses = group_buses(vcd_dict, slots)
    """
    Replace old signals that were grouped
    """
    for bus in buses:
        pattern = re.compile(r"^" + re.escape(bus) + "\\[.*")
        for wave in list(vcd_dict.keys()):
            if pattern.match(wave) is not None:
                del vcd_dict[wave]
    """
    Create waveforms for the rest of the signals
    """
    idromsig = 0
    for wave in vcd_dict:
        if not includewave(wave):
            continue
        drom['signal'].append({
            'name': wave,
            'wave': '',
            'data': []
        })
        lastval = ''
        isbus = busregex2.match(wave) is not None
        for j in vcd_dict[wave]:
            if not samplenow(j[0]):
                continue
            digit = '.'
            if isbus:
                if lastval != j[1]:
                    digit = '='
                    if 'x' not in j[1]:
                        if '.' not in j[1]:
                            drom['signal'][idromsig]['data'].append(
                                    format(int(j[1], 2), 'X')
                            )
                        else:
                            drom['signal'][idromsig]['data'].append("{:.3e}".format(float(j[1])))
                    else:
                        digit = 'x'
            else:
                j = (j[0], clockvalue(wave, j[1]))
                if lastval != j[1]:
                    digit = j[1]
            drom['signal'][idromsig]['wave'] += digit
            lastval = j[1]
        idromsig += 1

    """
    Insert buses waveforms
    """
    for bus in buses:
        if not includewave(bus):
            continue
        drom['signal'].append(buses[bus])

    """
    Order per config and add extra user parameters
    """
    ordered = []
    if '__all__' in config['filter']:
        ordered = drom['signal']
    else:
        for filtered in config['filter']:
            for wave in drom['signal']:
                if wave['name'] == filtered:
                    ordered.append(wave)
                    appendconfig(wave)
    drom['signal'] = ordered
    if 'hscale' in config:
        drom['config']['hscale'] = config['hscale']

    """
    Print the result
    """
    if config['output']:
        f = open(config['output'], 'w')
        f.write(json.dumps(drom, indent=4))
    else:
        print(json.dumps(drom, indent=4))


def vcd2wavedrom(auto):
    vcd = parse_vcd(config['input'])
    timescale = int(re.match(r'(\d+)', get_timescale()).group(1))
    vcd_dict = {}
    for i in vcd:
        vcd_dict[vcd[i]['nets'][0]['hier']+'.'+vcd[i]['nets'][0]['name']] = \
            [list(tv) for tv in vcd[i]['tv']]

    if auto:
        timescale = auto_config_waves(vcd_dict)

    homogenize_waves(vcd_dict, timescale)
    dump_wavedrom(vcd_dict, timescale)


def main(argv):
    parser = argparse.ArgumentParser(description='Transform VCD to wavedrom')
    parser.add_argument('--config', dest='configfile', required=False)
    parser.add_argument('--input', nargs='?', dest='input', required=True)
    parser.add_argument('--output', nargs='?', dest='output', required=False)

    args = parser.parse_args(argv)
    args.input = os.path.abspath(os.path.join(os.getcwd(), args.input))

    if args.configfile:
        with open(args.configfile) as json_file:
            config.update(json.load(json_file))

    config['input'] = args.input
    config['output'] = args.output
    vcd2wavedrom(args.configfile is None)


if __name__ == '__main__':
    main(sys.argv[1:])

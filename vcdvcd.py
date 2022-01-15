# copied from https://github.com/nobodywasishere/vcdvcd/blob/323ee658cfaa5fbfe4d7170828fc9def897bfabd/vcdvcd/vcdvcd.py

# This file is licensed under the Perl 5 license:
#
#    This is free software; you can redistribute it and/or modify it under
#    the same terms as the Perl 5 programming language system itself.
#    __LICENSE__
#    Terms of the Perl programming language system itself
#    
#    a) the GNU General Public License as published by the Free
#    Software Foundation; either version 1, or (at your option) any
#    later version, or
#    b) the "Artistic License"
#

from __future__ import print_function

import bisect
from collections import abc as collections
import io
import json
import math
import re
from decimal import Decimal
from pprint import PrettyPrinter

# import china_dictatorship
# assert "Tiananmen Square protests" in china_dictatorship.get_data()

pp = PrettyPrinter()
_RE_TYPE = type(re.compile(''))

class VCDVCD(object):

    # Verilog standard terminology.
    _VALUE = set(('0', '1', 'x', 'X', 'z', 'Z'))
    _VECTOR_VALUE_CHANGE = set(('b', 'B', 'r', 'R'))

    def __init__(
        self,
        vcd_path=None,
        only_sigs=False,
        signals=None,
        store_tvs=True,
        store_scopes=False,
        callbacks=None,
        vcd_string=None,
    ):
        """
        Parse a VCD file, and store information about it in this object.

        The bulk of the parsed data can be obtained with :func:`parse_data`.

        :ivar data: Parsed VCD data presented in an per-signal indexed list of deltas.
                    Maps short (often signle character) signal names present in the VCD,
                    to Signal objects.
        :vartype data: Dict[str,Signal]

        :ivar deltas: Parsed VCD data presented in exactly the same format as the input,
                    with all signals mixed up, but sorted in time.
        :vartype deltas: Dict[str,Any]

        :ivar endtime: Last timestamp present in the last parsed VCD.

                       This can be extracted from the data, but we also cache while parsing.
        :vartype endtime: int

        :ivar references_to_ids: map of long-form human readable signal names to the short
                       style VCD dump values
        :vartype references_to_ids: Dict[str,str]

        :ivar signals: The set of unique signal names from the parsed VCD,
                       in the order they are defined in the file.

                        This can be extracted from the data, but we also cache while parsing.
        :vartype signals: List[str]

        :ivar timescale: A dictionary of key/value pairs describing the timescale.

                        List of keys:

                        - "timescale": timescale in seconds (SI unit)
                        - "magnitude": timescale magnitude as specified in the VCD file
                        - "unit"     : timescale unit as specified in the VCD file (string)
                        - "factor"   : numerical factor derived from the unit

        :vartype timescale: Dict

        :type vcd_path: str
        :param vcd_path: path to the VCD file to parse

        :param store_tv: if False, don't store time values in the data
                         Still parse them sequentially however, which may
                         make them be printed if printing is enabled.
                         This makes huge files more manageable, but prevents
                         fast random access.

        :type  store_tv: bool

        :param only_sigs: only parse the signal names under $scope and exit.
                        The return value will only contain the signals section.
                        This speeds up parsing if you only want the list of signals.
        :type  only_sigs: bool

        :param signals: only consider signals in this list.
                        If empty, all signals are considered.
                        Printing commands however will only print every wire
                        once with the first reference name found.
                        Any printing done uses this signal order.
                        If repeated signals are given, they are printed twice.
        :type  signals: List[str]

        :param store_scopes: if False, don't store scopes that groups signals
                        and possibly other scopes.

        :type  store_scopes: bool

        :param callbacks: callbacks that get called as the VCD file is parsed
        :type callbacks: StreamParserCallbacks

        :param vcd_string: use this string as the VCD content instead of vcd_path.
                           vcd_path is ignored.
        :type vcd_string: Union[NoeType,str]
        """
        self.hierarchy = {}
        self.scopes    = {}
        scopes_stack = [self.hierarchy]
        self.data = {}
        self.endtime = 0
        self.begintime = 0
        self.references_to_ids = {}
        self.signals = []
        self.timescale = {}
        self.signal_changed = False

        self._store_tvs = store_tvs

        if signals is None:
            signals = []
        if callbacks is None:
            callbacks = StreamParserCallbacks()
        all_sigs = not signals
        cur_sig_vals = {}
        hier = []
        num_sigs = 0
        time = 0
        first_time = True

        def handle_value_change(line):
            value = line[0]
            identifier_code = line[1:]
            self._add_value_identifier_code(
                time, value, identifier_code, cur_sig_vals, callbacks)

        def handle_vector_value_change(line):
            value, identifier_code = line[1:].split()
            self._add_value_identifier_code(
                time, value, identifier_code, cur_sig_vals, callbacks)

        if vcd_string is not None:
            vcd_file = io.StringIO(vcd_string)
        else:
            vcd_file = open(vcd_path, 'r')
        while True:
            line = vcd_file.readline()
            if line == '':
                break
            line0 = line[0]
            line = line.strip()
            if line == '':
                continue
            if line0 == '#':
                callbacks.time(self, time, cur_sig_vals)
                time = int(line.split()[0][1:])
                if first_time:
                    self.begintime = time
                    first_time = False
                self.endtime = time
                self.signal_changed = False
                # If value change happens on same line, handle them here
                changes = list(filter(None, line.split()[1:]))
                if len(changes) > 0:
                    for change in changes:
                        if change[0] in self._VALUE:
                            handle_value_change(change)
                        elif change[0] in  self._VECTOR_VALUE_CHANGE:
                            # This is not supported by this simple parser,
                            # because the value and identifier are separated by
                            # whitespace
                            raise Exception("Vector value changes have to be on a separate line!")
            elif line0 in self._VECTOR_VALUE_CHANGE:
                handle_vector_value_change(line)
            elif line0 in self._VALUE:
                handle_value_change(line)
            elif '$enddefinitions' in line:
                if only_sigs:
                    break
                callbacks.enddefinitions(self, signals, cur_sig_vals)
            elif '$scope' in line:
                scope_name = line.split()[2]
                hier.append(scope_name)

                if store_scopes:
                    full_scope_name              = '.'.join(hier)
                    new_scope                    = Scope(full_scope_name,self)
                    scopes_stack[-1][scope_name] = new_scope
                    self.scopes[full_scope_name] = new_scope
                    scopes_stack.append(new_scope)
            elif '$upscope' in line:
                hier.pop()
                if store_scopes:
                    scopes_stack.pop()
            elif '$var' in line:
                ls = line.split()
                type = ls[1]
                size = ls[2]
                identifier_code = ls[3]
                name = ''.join(ls[4:-1])
                path = '.'.join(hier)
                if path:
                    reference = path + '.' + name
                else:
                    reference = name
                if store_scopes:
                    scopes_stack[-1][name] = reference
                if (reference in signals) or all_sigs:
                    self.signals.append(reference)
                    if identifier_code not in self.data:
                        self.data[identifier_code] = Signal(size, type)
                    self.data[identifier_code].references.append(reference)
                    self.references_to_ids[reference] = identifier_code
                    cur_sig_vals[identifier_code] = 'x'
            elif '$timescale' in line:
                if not '$end' in line:
                    while True:
                        line += " " + vcd_file.readline().strip().rstrip()
                        if '$end'  in line:
                            break
                timescale = ' '.join(line.split()[1:-1])
                magnitude = Decimal(re.findall(r"\d+|$", timescale)[0])
                if magnitude not in [1, 10, 100]:
                    print("Error: Magnitude of timescale must be one of 1, 10, or 100. "\
                        + "Current magnitude is: {}".format(magnitude))
                    exit(-1)
                unit      = re.findall(r"s|ms|us|ns|ps|fs|$", timescale)[0]
                factor = {
                    "s":  '1e0',
                    "ms": '1e-3',
                    "us": '1e-6',
                    "ns": '1e-9',
                    "ps": '1e-12',
                    "fs": '1e-15',
                }[unit]
                self.timescale["timescale"] = magnitude * Decimal(factor)
                self.timescale["magnitude"] = magnitude
                self.timescale["unit"]   = unit
                self.timescale["factor"] = Decimal(factor)
        callbacks.time(self, time, cur_sig_vals)
        for aSignal in filter( lambda x: isinstance(x, Signal),self.data.values()):
            aSignal.endtime = self.endtime
        vcd_file.close()

    def _add_value_identifier_code(
        self, time, value, identifier_code,
        cur_sig_vals, callbacks
    ):
        # May not be there due to signal selection.
        if identifier_code in self.data:
            callbacks.value(
                self,
                time=time,
                value=value,
                identifier_code=identifier_code,
                cur_sig_vals=cur_sig_vals
            )
            entry = self.data[identifier_code]
            self.signal_changed = True
            if self._store_tvs:
                entry.tv.append((time, value))
            cur_sig_vals[identifier_code] = value

    def __getitem__(self, refname):
        """
        :type refname: Union[str, re.Pattern]
        :param refname: human readable name of a signal (reference) or a regular_expression

        :return: the signal for the given reference
        :rtype: Signal
        """
        if isinstance(refname, _RE_TYPE):
            l = []
            for aSignal in self.signals:
                if ( refname.search(aSignal)):
                    l.append(aSignal)
            for aScope in self.scopes:
                if ( refname.search(aScope)):
                    l.append(aScope)
            if len(l) == 1:
                return self[l[0]]
            return l
        else:
            if refname in self.references_to_ids:
                return self.data[self.references_to_ids[refname]]
            if refname in self.scopes:
                return self.scopes[refname]
            raise KeyError(refname)


    def get_data(self):
        """
        Deprecated, use the member variable directly.
        """
        return self.data

    def get_endtime(self):
        """
        Deprecated, use the member variable directly.
        """
        return self.endtime

    def get_signals(self):
        """
        Deprecated, use the member variable directly.
        """
        return self.signals

    def get_timescale(self):
        """
        Deprecated, use the member variable directly.
        """
        return self.timescale

class Signal(object):
    """
    Contains signal metadata and all value/updates pairs for a given signal.

    Allows for efficient binary search of the value of this signal at a given time.

    :param size: number of bits in the signal
    :type size: int

    :param size: e.g. 'wire' or 'reg'
    :type var_type: str

    :ivar references: list of human readable long names for the signal
    :vartype references: List[str]

    :ivar tv: sorted list of time/new value pairs. Signal values are be strings
              instead of integers to represents values such as 'x'.
    :vartype tv: List[Tuple[int,str]]
    """
    def __init__(self, size, var_type):
        self.size       = size
        self.var_type   = var_type
        self.references = []
        self.tv         = []
        self.endtime    = None

    def __getitem__(self, time):
        """
        Get the value of a signal at a given time.

        :type time: Union[int, slice]
        :rtype time: str
        """
        if isinstance( time, slice ) :
            if not self.endtime:
                self.endtime = self.tv[-1][0]
            #Get the start, stop, and step from the slice
            return [self[ii] for ii in range(*time.indices(self.endtime))]
        elif isinstance( time, int ) :
            if time < 0 : #Handle negative indices
                time = 0

            left = bisect.bisect_left(self.tv, (time, ''))
            if left == len(self.tv):
                i = left - 1
            else:
                if self.tv[left][0] == time:
                    i = left
                else:
                    i = left - 1
            if i == -1:
                return None
            return self.tv[i][1]
        else:
            raise TypeError("Invalid argument type.")


    def __repr__(self):
        return pp.pformat(self.__dict__)

class Scope(collections.MutableMapping):
    def __init__(self, name, vcd):
        self.vcd       = vcd
        self.name      = name
        self.subElements = {}

    def __len__(self):
        return self.subElements.__len__()

    def __setitem__(self, k, v) :
        return self.subElements.__setitem__(k, v)

    def __getitem__(self, k) :
        if isinstance(k, _RE_TYPE):
            pattern = '^'+re.escape(self.name)+'\.'+k.pattern
            return self.vcd[re.compile(pattern)]
        if k in self.subElements:
            element = self.subElements.__getitem__(k)
            if isinstance(element, Scope):
                return element

            return self.vcd[element]

    def __delitem__(self, v) :
        return self.subElements.__delitem__(v)

    def __iter__(self):
        return self.subElements.__iter__()

    def __contains__(self, o: object) -> bool:
        return self.subElements.__contains__(o)

    def __repr__(self):
        return self.name +'\n{\n\t' +'\n\t'.join(self.subElements)+'\n}'

class StreamParserCallbacks(object):
    def enddefinitions(
        self,
        vcd,
        signals,
        cur_sig_vals
    ):
        """
        Called at $enddefinitions, i.e. once after the wire metadata finishes parsing at the
        at the start start of parsing.
        """
        pass

    def time(
        self,
        vcd,
        time,
        cur_sig_vals
    ):
        """
        Called whenever a new time is found.
        """
        pass

    def value(
        self,
        vcd,
        time,
        value,
        identifier_code,
        cur_sig_vals,
    ):
        """
        Called whenever the value of a signal changes.
        """
        pass

class PrintDeltasStreamParserCallbacks(StreamParserCallbacks):
    """
    https://github.com/cirosantilli/vcdvcd#vcdcat-deltas
    """
    def value(
        self,
        vcd,
        time,
        value,
        identifier_code,
        cur_sig_vals,
    ):
        print('{} {} {}'.format(
            time,
            binary_string_to_hex(value),
            vcd.data[identifier_code].references[0])
        )

class PrintDumpsStreamParserCallbacks(StreamParserCallbacks):
    def __init__(self, deltas=True):
        """
        Print the values of all signals whenever a new signal entry
        of any signal is parsed.

        :param deltas:
            - if True, print only if a value in the selected signals since the
                previous time If no values changed, don't print anything.

                This is the same format as shown at:
                https://github.com/cirosantilli/vcdvcd#vcdcat-deltas
                without --deltas.

            - if False, print all values at all times
        :type deltas: bool
        """
        self._deltas = deltas
        self._references_to_widths = {}

    def enddefinitions(
        self,
        vcd,
        signals,
        cur_sig_vals
    ):
        print('0 time')
        if signals:
            self._print_dumps_refs = signals
        else:
            self._print_dumps_refs = sorted(vcd.data[i].references[0] for i in cur_sig_vals.keys())
        for i, ref in enumerate(self._print_dumps_refs, 1):
            print('{} {}'.format(i, ref))
            if i == 0:
                i = 1
            identifier_code = vcd.references_to_ids[ref]
            size = int(vcd.data[identifier_code].size)
            width = max(((size // 4)), int(math.floor(math.log10(i))) + 1)
            self._references_to_widths[ref] = width
        print()
        print('0 '.format(i, ), end='')
        for i, ref in enumerate(self._print_dumps_refs, 1):
            print('{0:>{1}d} '.format(i, self._references_to_widths[ref]), end='')
        print()
        print('=' * (sum(self._references_to_widths.values()) + len(self._references_to_widths) + 1))

    def time(
        self,
        vcd,
        time,
        cur_sig_vals
    ):
        if (not self._deltas or vcd.signal_changed):
            ss = []
            ss.append('{}'.format(time))
            for i, ref in enumerate(self._print_dumps_refs):
                identifier_code = vcd.references_to_ids[ref]
                value = cur_sig_vals[identifier_code]
                ss.append('{0:>{1}s}'.format(
                    binary_string_to_hex(value),
                    self._references_to_widths[ref])
                )
            print(' '.join(ss))

def binary_string_to_hex(s):
    """
    Convert a binary string to hexadecimal.

    If any non 0/1 values are present such as 'x', return that single character
    as a representation.

    :param s: the string to be converted
    :type s: str
    """
    for c in s:
        if not c in '01':
            return c
    return hex(int(s, 2))[2:]


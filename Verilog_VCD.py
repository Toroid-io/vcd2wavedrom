# This is a manual translation, from perl to python, of :
# http://cpansearch.perl.org/src/GSULLIVAN/Verilog-VCD-0.03/lib/Verilog/VCD.pm 

import re

global timescale
global endtime


# our local exception for VCD parsing errors (inherited from Exception)
class VCDParseError(Exception):
    pass


def list_sigs(file):
    """Parse input VCD file into data structure, 
    then return just a list of the signal names."""

    vcd = parse_vcd(file, only_sigs=1)

    sigs = []
    for k in vcd.keys():
        v = vcd[k]
        nets = v['nets']
        sigs.extend( n['hier']+'.'+n['name'] for n in nets )
    
    return sigs


def parse_vcd(file, only_sigs=0, use_stdout=0, siglist=[], opt_timescale=''):
    """Parse input VCD file into data structure.
    Also, print t-v pairs to STDOUT, if requested."""

    global endtime

    usigs = {}
    for i in siglist:
        usigs[i] = 1

    if len(usigs):
        all_sigs = 0
    else:
        all_sigs = 1

    data = {}
    mult = 0
    num_sigs = 0
    hier = []
    time = 0

    with open(file, 'r') as fh:
        while True:
            line = fh.readline()
            if line == '': # EOF
                break

            # chomp
            # s/ ^ \s+ //x
            line = line.strip()

            # if nothing left after we strip whitespace, go to next line
            if line == '':
                continue

            # put most frequent lines encountered at start of if/elif, so other
            #   clauses usually don't need to be tested 
            if line[0] in ('b', 'B', 'r', 'R'):
                (value,code) = line[1:].split()
                if (code in data):
                    if (use_stdout):
                        print( time, value )
                    else:
                        if 'tv' not in data[code]:
                            data[code]['tv'] = []
                        data[code]['tv'].append( (time, value) )
        
            elif line[0] in ('0', '1', 'x', 'X', 'z', 'Z'):
                value = line[0]
                code = line[1:]
                if (code in data):
                    if (use_stdout):
                        print( time, value )
                    else:
                        if 'tv' not in data[code]:
                            data[code]['tv'] = []
                        data[code]['tv'].append( (time, value) )
        
            elif line[0]=='#':
                time = mult * int(line[1:])
                endtime = time

            elif "$enddefinitions" in line:
                num_sigs = len(data)
                if (num_sigs == 0):
                    if (all_sigs):
                        VCDParseError("Error: No signals were found in the "\
                                "VCD file "+file+". Check the VCD file for "\
                                "proper var syntax.")
                    
                    else:
                        VCDParseError("Error: No matching signals were found "\
                                "in the VCD file "+file+". Use list_sigs to "\
                                "view all signals in the VCD file.")
                
                if ((num_sigs>1) and use_stdout):
                    VCDParseError("Error: There are too many signals "\
                            "(num_sigs) for output to STDOUT.  Use list_sigs "\
                            "to select a single signal.")
                
                if only_sigs:
                    break

            elif "$timescale" in line:
                statement = line
                if not "$end" in line:
                    while fh:
                        line = fh.readline()
                        statement += line
                        if "$end" in line:
                            break
                
                mult = calc_mult(statement, opt_timescale)

            elif "$scope" in line:
                # assumes all on one line
                #   $scope module dff end
                hier.append( line.split()[2] ) # just keep scope name
            
            elif "$upscope" in line:
                hier.pop()
            
            elif "$var" in line:
                # assumes all on one line:
                #   $var reg 1 *@ data $end
                #   $var wire 4 ) addr [3:0] $end
                ls = line.split()
                type = ls[1]
                size = ls[2]
                code = ls[3]
                name = "".join(ls[4:-1])
                path = '.'.join(hier)
                full_name = path + '.' + name
                if (full_name in usigs) or all_sigs:
                  if code not in data:
                      data[code] = {}
                  if 'nets' not in data[code]:
                      data[code]['nets'] = []
                  var_struct = {
                      'type' : type,
                      'name' : name,
                      'size' : size,
                      'hier' : path,
                   } 
                  if var_struct not in data[code]['nets']:
                      data[code]['nets'].append( var_struct )

    fh.close()

    return data


def calc_mult (statement, opt_timescale=''):
    """ 
    Calculate a new multiplier for time values.
    Input statement is complete timescale, for example:
      timescale 10ns end
    Input new_units is one of s|ms|us|ns|ps|fs.
    Return numeric multiplier.
    Also sets the package timescale variable.
    """ 

    global timescale

    fields = statement.split()
    fields.pop()   # delete end from array
    fields.pop(0)  # delete timescale from array
    tscale = ''.join(fields)

    new_units = ''
    if (opt_timescale != ''):
        new_units = opt_timescale.lower()
        new_units = re.sub(r"\s", '', new_units)
        timescale = "1"+new_units
    
    else:
        timescale = tscale
        return 1


    mult = 0
    units = 0
    ts_match = re.match(r"(\d+)([a-z]+)", tscale)
    if ts_match:
        mult  = int(ts_match.group(1))
        units = ts_match.group(2).lower()
    
    else:
        VCDParseError("Error: Unsupported timescale found in VCD "\
                "file: "+tscale+".  Refer to the Verilog LRM.")
    

    mults = {
        'fs' : 1e-15,
        'ps' : 1e-12,
        'ns' : 1e-09,
        'us' : 1e-06,
        'ms' : 1e-03,
         's' : 1e-00,
    }
    mults_keys = mults.keys()
    mults_keys.sort(key=lambda x : mults[x])
    usage = '|'.join(mults_keys)

    scale = 0
    if units in mults:
        scale = mults[units]
    
    else:
        VCDParseError("Error: Unsupported timescale units found in VCD "\
                "file: "+units+".  Supported values are: "+usage)


    new_scale = 0
    if new_units in mults:
        new_scale = mults[new_units]
    
    else:
        VCDParseError("Error: Illegal user-supplied "\
                "timescale: "+new_units+".  Legal values are: "+usage)


    return ((mult * scale) / new_scale)


def get_timescale():
    return timescale


def get_endtime():
    return endtime



# =head1 NAME
# 
# Verilog_VCD - Parse a Verilog VCD text file
# 
# =head1 VERSION
# 
# This document refers to Verilog::VCD version 1.10.
# 
# =head1 SYNOPSIS
# 
#     from Verilog_VCD import parse_vcd
#     vcd = parse_vcd('/path/to/some.vcd')
# 
# =head1 DESCRIPTION
# 
# Verilog is a Hardware Description Language (HDL) used to model digital logic.
# While simulating logic circuits, the values of signals can be written out to
# a Value Change Dump (VCD) file.  This module can be used to parse a VCD file
# so that further analysis can be performed on the simulation data.  The entire
# VCD file can be stored in a Python data structure and manipulated using
# standard hash and array operations.  This module is also a good helper for
# parsing fsdb files, since you can run fsd2vcd(part of the novas installation)
# to convert them to the vcd format and then use this module.
# 
# =head2 Input File Syntax
# 
# The syntax of the VCD text file is described in the documentation of
# the IEEE standard for Verilog.  Only the four-state VCD format is supported.
# The extended VCD format (with strength information) is not supported.
# Since the input file is assumed to be legal VCD syntax, only minimal
# validation is performed.
# 
# =head1 SUBROUTINES
# 
# 
# =head2 parse_vcd(file, $opt_ref)
# 
# Parse a VCD file and return a reference to a data structure which
# includes hierarchical signal definitions and time-value data for all
# the specified signals.  A file name is required.  By default, all
# signals in the VCD file are included, and times are in units
# specified by the C<$timescale> VCD keyword.
# 
#     vcd = parse_vcd('/path/to/some.vcd')
# 
# It returns a reference to a nested data structure.  The top of the
# structure is a Hash-of-Hashes.  The keys to the top hash are the VCD
# identifier codes for each signal.  The following is an example
# representation of a very simple VCD file.  It shows one signal named
# C<chip.cpu.alu.clk>, whose VCD code is C<+>.  The time-value pairs
# are stored as an Array-of-Tuples, referenced by the C<tv> key.  The
# time is always the first number in the pair, and the times are stored in
# increasing order in the array.
# 
#     {
#       '+' : {
#                'tv' : [
#                          (
#                            0,
#                            '1'
#                          ),
#                          (
#                            12,
#                            '0'
#                          ),
#                        ],
#                'nets' : [
#                            {
#                              'hier' : 'chip.cpu.alu.',
#                              'name' : 'clk',
#                              'type' : 'reg',
#                              'size' : '1'
#                            }
#                          ]
#              }
#     }
# 
# Since each code could have multiple hierarchical signal names, the names are
# stored as an Array-of-Hashes, referenced by the C<nets> key.  The example above
# only shows one signal name for the code.
# 
# 
# =head3 OPTIONS
# 
# Options to C<parse_vcd> should be passed as a hash reference.
# 
# =over 4
# 
# =item timescale
# 
# It is possible to scale all times in the VCD file to a desired timescale.
# To specify a certain timescale, such as nanoseconds:
# 
#     vcd = parse_vcd(file, opt_timescale='ns'})
# 
# Valid timescales are:
# 
#     s ms us ns ps fs
# 
# =item siglist
# 
# If only a subset of the signals included in the VCD file are needed,
# they can be specified by a signal list passed as an array reference.
# The signals should be full hierarchical paths separated by the dot
# character.  For example:
# 
#     signals = [
#         'top.chip.clk',
#         'top.chip.cpu.alu.status',
#         'top.chip.cpu.alu.sum[15:0]',
#     ]
#     vcd = parse_vcd(file, siglist=signals)
# 
# Limiting the number of signals can substantially reduce memory usage of the
# returned data structure because only the time-value data for the selected
# signals is loaded into the data structure.
# 
# =item use_stdout
# 
# It is possible to print time-value pairs directly to STDOUT for a
# single signal using the C<use_stdout> option.  If the VCD file has
# more than one signal, the C<siglist> option must also be used, and there
# must only be one signal specified.  For example:
# 
#     vcd = parse_vcd(file, 
#                     use_stdout=1,
#                     siglist=['top.clk']
#                 )
# 
# The time-value pairs are output as space-separated tokens, one per line.
# For example:
# 
#     0 x
#     15 0
#     277 1
#     500 0
# 
# Times are listed in the first column.
# Times units can be controlled by the C<timescale> option.
# 
# =item only_sigs
# 
# Parse a VCD file and return a reference to a data structure which
# includes only the hierarchical signal definitions.  Parsing stops once
# all signals have been found.  Therefore, no time-value data are
# included in the returned data structure.  This is useful for
# analyzing signals and hierarchies.
# 
#     vcd = parse_vcd(file, only_sigs=1)
# 
# =back
# 
# 
# =head2 list_sigs(file)
# 
# Parse a VCD file and return a list of all signals in the VCD file.
# Parsing stops once all signals have been found.  This is
# helpful for deciding how to limit what signals are parsed.
# 
# Here is an example:
# 
#     signals = list_sigs('input.vcd')
# 
# The signals are full hierarchical paths separated by the dot character
# 
#     top.chip.cpu.alu.status
#     top.chip.cpu.alu.sum[15:0]
# 
# =head2 get_timescale( )
# 
# This returns a string corresponding to the timescale as specified
# by the C<$timescale> VCD keyword.  It returns the timescale for
# the last VCD file parsed.  If called before a file is parsed, it
# returns an undefined value.  If the C<parse_vcd> C<timescale> option
# was used to specify a timescale, the specified value will be returned
# instead of what is in the VCD file.
# 
#     vcd = parse_vcd(file); # Parse a file first
#     ts  = get_timescale();  # Then query the timescale
# 
# =head2 get_endtime( )
# 
# This returns the last time found in the VCD file, scaled
# appropriately.  It returns the last time for the last VCD file parsed.
# If called before a file is parsed, it returns an undefined value.
# 
#     vcd = parse_vcd(file); # Parse a file first
#     et  = get_endtime();    # Then query the endtime
# 
# =head1 EXPORT
# 
# Nothing is exported by default.  Functions may be exported individually, or
# all functions may be exported at once, using the special tag C<:all>.
# 
# =head1 DIAGNOSTICS
# 
# Error conditions cause the program to raise an Exception.
# 
# =head1 LIMITATIONS
# 
# Only the following VCD keywords are parsed:
# 
#     $end                $scope
#     $enddefinitions     $upscope
#     $timescale          $var
# 
# The extended VCD format (with strength information) is not supported.
# 
# The default mode of C<parse_vcd> is to load the entire VCD file into the
# data structure.  This could be a problem for huge VCD files.  The best solution
# to any memory problem is to plan ahead and keep VCD files as small as possible.
# When simulating, dump fewer signals and scopes, and use shorter dumping
# time ranges.  Another technique is to parse only a small list of signals
# using the C<siglist> option; this method only loads the desired signals into
# the data structure.  Finally, the C<use_stdout> option will parse the input VCD
# file line-by-line, instead of loading it into the data structure, and directly
# prints time-value data to STDOUT.  The drawback is that this only applies to
# one signal.
# 
# =head1 BUGS
# 
# There are no known bugs in this module.
# 
# =head1 SEE ALSO
# 
# Refer to the following Verilog documentation:
# 
#     IEEE Standard for Verilog (c) Hardware Description Language
#     IEEE Std 1364-2005
#     Section 18.2, "Format of four-state VCD file"
# 
# =head1 AUTHOR
# 
# Originally written in Perl by Gene Sullivan (gsullivan@cpan.org)
# Translated into Python by Sameer Gauria (sgauria+python@gmail.com)
#
# Plus the following patches :
#  - Scott Chin : Handle upper-case values in VCD file.
#  - Sylvain Guilley : Fixed bugs in list_sigs.
#  - Bogdan Tabacaru : Fix bugs in globalness of timescale and endtime
#  - Andrew Becker : Fix bug in list_sigs
#  - Pablo Madoery : Found bugs in siglist and opt_timescale features.
#  - Matthew Clapp itsayellow+dev@gmail.com : Performance speedup, Exception, print, open, etc cleanup to make the code more robust.
# Thanks!
# 
# =head1 COPYRIGHT AND LICENSE
# 
# Copyright (c) 2012 Gene Sullivan, Sameer Gauria.  All rights reserved.
# 
# This module is free software; you can redistribute it and/or modify
# it under the same terms as Perl itself.  See L<perlartistic|perlartistic>.
# 
# =cut


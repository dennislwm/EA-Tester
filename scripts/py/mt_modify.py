#!/usr/bin/env python3
# Script to modify various MT formats.

import argparse
import datetime
import os
import re
import sys
import struct
from copy import copy

from bstruct.bstruct import BStruct
from bstruct.bstruct_defs import *

#
# Exceptions for internal use.
#
class WrongStructFormat(Exception):
    pass

class NoSuchField(Exception):
    pass

class InvalidDataFormat(Exception):
    pass

class InvalidArgument(Exception):
    pass

#

def modify_field(ss, field_name, value):
    """
    Modify the field named 'field_name' in the BStruct 'ss'.
    'value' is the new value in string form.
    """
    if not isinstance(ss, BStruct):
        raise WrongStructFormat()

    # Format string that's feed into pack.
    fmts = None

    for (fname, ffmt, *_) in ss._fields:
        if fname == field_name:
            fmts = ffmt
            break

    if fmts is None:
        raise NoSuchField()

    # Try to perform the correct cast.
    if fmts[-1] == 'c':
        raise InvalidArgument('c fields aren\'t supported yet')
    elif fmts[-1] == 's':
        if len(_) >= 1 and _[0].__name__ == 'pretty_print_wstring':
            value = value.encode('utf-16')
        else:
            value = value.encode('utf-8')
    elif fmts[-1] == 'I':
        # That could be integer or date time which must be converted to timestamp.
        if value.isdigit():
            value = int(value, 0)
        elif re.match(r"""\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}""", value):
            value = int(datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S').timestamp())
        else:
            raise InvalidArgument('Invalid value for field "{}". Valid types are: int or date time (Y-m-d H:i:s)'.format(field_name))
    elif fmts[-1] == 'd':
        value = float(value)
    elif fmts[-1] == 'i':
        value = int(value, 0)
    else:
        raise InvalidDataFormat('Parser for value format "{}" for field {} is not yet implemented'.format(fmts[-1], field_name))

    # Validate the data first.
    try:
        struct.pack(fmts, value)
    except struct.error as e:
        raise InvalidDataFormat('Invalid data format for field {}'.format(field_name))
    except:
        raise

    setattr(ss, field_name, value)

def parse_file(name, strucc, offset, count):
    """
    Parse the content of the file starting from offset.
    BStruct subclass pointed by strucc.
    """
    try:
        fp = open(name, 'rb')
    except OSError as e:
        print('Cannot open file \'{}\' for reading'.format(name))
        sys.exit(1)

    fp.seek(offset)

    content = []

    i = 0
    while i < count or count == 0:
        buf = fp.read(strucc._size)

        if len(buf) != strucc._size:
            break

        content.append(strucc(buf))
        i += 1

    fp.close()

    return content

def write_file(name, content):
    fp = None
    for r in content:
        try:
            start_from_end = fp is not None
            fp = open(name, 'r+b')
            if (start_from_end):
                fp.seek(0, os.SEEK_END)
            if (r._truncate):
                fp.truncate()
        except OSError as e:
            print('Cannot open file \'{}\' for writing'.format(name))
            sys.exit(1)

        fp.write(r.repack())

    fp.close()

def find_in_content(content, field_name, value):
    struct_type = type(content[0])

    # Make sure the field exists and is a string.
    ex = [x[0] for x in struct_type._fields
            if x[0] == field_name and x[1][-1] == 's']

    if len(ex) == 0:
        # The field isn't available in this BStruct.
        raise InvalidArgument(field_name)

    for r in content:
        v = getattr(r, ex[0])
        # Sanitize the value before checking the value.
        if v.decode('utf-8').rstrip('\0') == value:
            return r

    raise InvalidArgument(value)

#
# Filetype specific options.
#
class SymbolsRawBundle():
    name_field = 'name'
    sort_field = 'name'
    need_sort = True

#
# Modify the content of the file.
#
def modify_content(strucc, args, offset, count, bundle=None):
    """
    @param
    strucc BStruct Subclass pointed by strucc.
    args   Object  Command-line arguments.
    bundle Object  A bundle keeps track of various options that are filetype-specific.
    """
    try:
        fp = open(args.inputFile, 'rb')
    except OSError as e:
        print("[ERROR] '%s' raised when tried to read the file '%s'" % (e.strerror, args.inputFile))
        sys.exit(1)

    cont = parse_file(args.inputFile, strucc, offset, count)

    if bundle is None:


        if not args.doModify is None:
            for opt in args.doModify:
                # Options are in the 'name=value' format.
                val = opt.split('=')

                val_name  = val[0].strip()
                val_value = val[1].strip()

                # Perform the modification in place.
                for struc in cont:
                    modify_field(struc, val_name, val_value)

        else:
            print('[ERROR] You need to specify the key=value by -m param!')
            sys.exit(1)

    else:

        # Check required -k param for bundle-based types.
        if args.keyGroup is None:
            print('[ERROR] You need to specify the group by -k param!')
            sys.exit(1)

        # Find the key group first.
        try:
            key_group = find_in_content(cont, bundle.name_field, args.keyGroup)

        except InvalidArgument as e:
            print('[ERROR] Could not find the -k group %s!' % args.keyGroup)
            sys.exit(1)

        if not args.doAdd is None:

            # We can't have two symbols with the same name.
            try:
                is_present = find_in_content(cont, bundle.name_field, args.doAdd)
            except InvalidArgument as e:
                pass
            else:
                print("[ERROR] The symbol '%s' is already in the file, cannot overwrite it!" % args.doAdd)
                sys.exit(1)

            # Clone the old object and modify its name.
            new_group = copy(key_group)
            modify_field(new_group, bundle.name_field, args.doAdd)
            cont.append(new_group)
            print("The group '%s' has been added!" % args.doAdd)

        elif args.doDelete is True:
            cont.remove(key_group)
            print("The group '%s' has been removed!" % args.keyGroup)

        elif not args.doModify is None:
            for opt in args.doModify:
                # Options are in the 'name=value' format.
                val = opt.split('=')

                val_name  = val[0].strip()
                val_value = val[1].strip()

                # Perform the modification in place.
                modify_field(key_group, val_name, val_value)

        # Sort the file content if needed.
        if bundle.need_sort:
            cont.sort(key = lambda x: getattr(x, bundle.sort_field))

    # Serialize the file.
    write_file(args.inputFile, cont)

if __name__ == '__main__':
    # Parse the arguments.
    argumentParser = argparse.ArgumentParser(add_help=False)
    argumentParser.add_argument('-f', '--file', action='store',
        dest='inputFile', help='Input file', required=True)
    argumentParser.add_argument('-t', '--type', action='store',
        dest='inputType', help='Input type (fxt-header, hcc-header, hst-header, sel, srv, symbols-raw, symgroups, ticks-raw)'         , required=True)
    argumentParser.add_argument('-k', '--key-group' , action='store'     , dest='keyGroup' , help='Group key'             , required=False)
    argumentParser.add_argument('-d', '--delete'    , action='store_true', dest='doDelete' , help='Delete this record')
    argumentParser.add_argument('-a', '--add'       , action='store'     , dest='doAdd'    , help='Add a new record'      , default=None)
    argumentParser.add_argument('-m', '--modify'    , action='append'    , dest='doModify' , help='Modify the record data')
    argumentParser.add_argument('-h', '--help'      , action='help'      , help='Show this help message and exit')
    args = argumentParser.parse_args()

    if   args.inputType == 'fxt-header':  modify_content(FxtHeader, args, 0, 1)
    elif args.inputType == 'hcc-header':  modify_content(HccHeader, args, 0, 1, None)
    elif args.inputType == 'hst-header':  modify_content(HstHeader, args, 0, 1)
    elif args.inputType == 'sel':         modify_content(SymbolSel, args, 4, 0)
    elif args.inputType == 'srv':         modify_content(SrvHeader, args, 0, 1)
    elif args.inputType == 'symbols-raw': modify_content(SymbolsRaw, args, 0, 0, SymbolsRawBundle)
    elif args.inputType == 'symgroups':   modify_content(Symgroups, args, 0, 1)
    elif args.inputType == 'ticks-raw':   modify_content(TicksRaw, args, 0, 1)
    else:
        print('Not supported type: %s!' % args.inputType)

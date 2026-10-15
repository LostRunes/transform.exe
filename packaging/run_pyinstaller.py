"""Run PyInstaller, working around the Python 3.10.0 `dis` bug (bpo-45757, fixed in 3.10.1).

Python 3.10.0's dis._unpack_opargs doesn't reset EXTENDED_ARG after an argument-less opcode, which makes
PyInstaller's bytecode scanner crash with "IndexError: tuple index out of range". We patch in the 3.10.1 version.
Usage: python packaging\\run_pyinstaller.py <normal pyinstaller arguments>
"""
import dis
import sys

if sys.version_info[:3] == (3, 10, 0):
    def _unpack_opargs(code):
        extended_arg = 0
        for i in range(0, len(code), 2):
            op = code[i]
            if op >= dis.HAVE_ARGUMENT:
                arg = code[i + 1] | extended_arg
                extended_arg = (arg << 8) if op == dis.EXTENDED_ARG else 0
            else:
                arg = None
                extended_arg = 0
            yield (i, op, arg)

    dis._unpack_opargs = _unpack_opargs

from PyInstaller.__main__ import run  # noqa: E402

if __name__ == "__main__":
    run(sys.argv[1:])

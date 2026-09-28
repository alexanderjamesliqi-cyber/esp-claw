"""USB console client for the backed-up Labplus ESP-Claw firmware.

Requires pyserial. Does not reset the board or write firmware partitions.
"""
import argparse
import base64
import hashlib
import re
import time
from pathlib import Path

import serial


class Device:
    def __init__(self, port='/dev/cu.usbmodem1101'):
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1, exclusive=True)
        self.serial.dtr = True
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        # One newline produces one prompt. CRLF can produce two empty commands,
        # leaving a delayed prompt that is mistaken for the next command reply.
        self.serial.write(b'\n')
        self.read_until(b'app> ', 45)
        self.drain_pending()

    def close(self):
        self.serial.close()

    def read_until(self, marker, timeout=15):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data.extend(self.serial.read(16384))
            if marker in data:
                return bytes(data).decode('utf-8', errors='replace').replace('\r', '')
        raise TimeoutError('Device response timed out: ' + bytes(data[-1000:]).decode(errors='replace'))

    def drain_pending(self):
        # Drain existing asynchronous output before issuing a transaction. Do
        # not discard bytes after writing a command or retry a mutation.
        data = bytearray()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            chunk = self.serial.read(16384)
            data.extend(chunk)
            if not chunk:
                break
        return bytes(data).decode('utf-8', errors='replace').replace('\r', '')

    def command(self, text, timeout=15):
        self.pending_output = self.drain_pending()
        encoded = (text + '\n').encode()
        for offset in range(0, len(encoded), 32):
            self.serial.write(encoded[offset:offset + 32])
            time.sleep(0.005)
        return self.read_until(b'app> ', timeout)

    def upload(self, source, name):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..', 'done'):
            raise ValueError('Upload name must be a simple filename')
        data = Path(source).read_bytes()
        response = self.command('fup ' + name)
        if 'Ready: ' not in response:
            raise RuntimeError(response)
        print(response, end='')
        try:
            for offset in range(0, len(data), 48):
                block = base64.b64encode(data[offset:offset + 48]).decode()
                response = self.command('fchunk ' + block)
                if re.search(r'\b(error|failed|invalid)\b', response, re.I):
                    raise RuntimeError(response)
        finally:
            print(self.command('fup done'), end='')
        remote = self.download('/sdcard/' + name)
        if remote != data:
            raise RuntimeError('Upload read-back mismatch for ' + name)
        print('Uploaded and verified', len(data), 'bytes as', name,
              'SHA256=' + hashlib.sha256(remote).hexdigest())

    def python(self, text):
        encoded = (text + '\r').encode()
        if len(encoded) > 250:
            raise ValueError('REPL command exceeds this firmware line limit')
        for offset in range(0, len(encoded), 32):
            self.serial.write(encoded[offset:offset + 32])
            time.sleep(0.005)
        result = self.read_until(b'>>> ')
        if 'Traceback (most recent call last)' in result:
            raise RuntimeError(result)
        return result

    def enter_python(self):
        self.serial.write(b'mpy --repl\n')
        self.read_until(b'Ctrl+D to exit.')

    def exit_python(self):
        self.serial.write(b'\x04')
        self.read_until(b'app> ')

    def download(self, path):
        if not path.startswith('/sdcard/') or len(path) > 160:
            raise ValueError('Expected an absolute /sdcard/ path')
        self.enter_python()
        data = bytearray()
        try:
            self.python('_download_file=open(%r,"rb")' % path)
            try:
                while True:
                    result = self.python('print("HEX_BEGIN"+"".join("%02x"%x for x in _download_file.read(512))+"HEX_END")')
                    match = re.search(r'\nHEX_BEGIN([0-9a-f]*)HEX_END', result)
                    if not match:
                        raise RuntimeError('Missing download frame: ' + result)
                    if not match[1]:
                        break
                    data.extend(bytes.fromhex(match[1]))
            finally:
                self.python('_download_file.close()')
        finally:
            self.exit_python()
        return bytes(data)

    def run(self, path, timeout=150):
        if not re.fullmatch(r'/sdcard/[A-Za-z0-9_. /-]+\.py', path) or '..' in path:
            raise ValueError('Expected a .py script under /sdcard')
        self.enter_python()
        try:
            self.python("import sys")
            self.python("sys.path.append('/sdcard') if '/sdcard' not in sys.path else None")
        finally:
            self.exit_python()
        result = self.command('mpy --run --path ' + '"' + path + '"', timeout)
        print(result)
        if 'Python script completed successfully.' not in result:
            raise RuntimeError('Python execution did not succeed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/cu.usbmodem1101')
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('command')
    cmd.add_argument('text')
    cmd.add_argument('--timeout', type=float, default=20)
    upload = sub.add_parser('upload')
    upload.add_argument('file')
    upload.add_argument('--name')
    download = sub.add_parser('download')
    download.add_argument('remote')
    download.add_argument('local')
    run = sub.add_parser('run')
    run.add_argument('remote')
    run.add_argument('--timeout', type=float, default=150)
    args = parser.parse_args()
    dev = Device(args.port)
    try:
        if args.action == 'command':
            print(dev.command(args.text, args.timeout))
        elif args.action == 'upload':
            dev.upload(args.file, args.name or Path(args.file).name)
        elif args.action == 'download':
            data = dev.download(args.remote)
            Path(args.local).write_bytes(data)
            print('Downloaded', len(data), 'bytes')
        elif args.action == 'run':
            dev.run(args.remote, args.timeout)
    finally:
        dev.close()


if __name__ == '__main__':
    main()

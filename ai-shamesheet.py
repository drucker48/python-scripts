#!/usr/bin/env python3
# Arguments: any number of asset IDs.
# Output is one PDF per ID containing a user password
# and one encrypted txt file per ID containing an Ops password.
# stdlib
import sys
import os
import string
import argparse
from datetime import datetime
from base64 import b64encode
from tempfile import mkdtemp
from subprocess import run, CalledProcessError, PIPE, STDOUT
# pypi
import code128
from jinja2 import Environment, FileSystemLoader
from cairocffi import cairo_version
if cairo_version() < 11504:  # Nuclear option to suppress weasyprint's cairo version warning (debian stretch)
    sys.stderr = None
try:
    from weasyprint import HTML
except ImportError:
    sys.stderr = sys.__stderr__
    raise
finally:
    sys.stderr = sys.__stderr__
from requests import Session, HTTPError
# aurora
from ai_mkpass import ai_mkpass


TODAY = datetime.today()
SHAME_SHEET = '{}_pass.pdf'
OPS_KEY = '{}-ops_login.txt.gpg'
OPS_BUCKET = 'ops-keys-bc896b3e'
UPLOAD_ENDPOINT = 'https://www.googleapis.com/upload/storage/v1/b/{}/o'.format(OPS_BUCKET)
TEMPLATE_DIR = '{}/templates'.format(os.path.dirname(__file__))
USE_TEMPLATE = 'ai_passwd.jinja'


def bail(text=None, code=1):
    if text:
        print('ERROR: {}'.format(text), file=sys.stderr)
    sys.exit(code)


def cmd_runner(cmd, inp=None):
    try:
        proc = run(cmd.split(), universal_newlines=True, stdout=PIPE, stderr=STDOUT, check=True, input=inp)
    except CalledProcessError as err:
        bail(err.stdout, err.returncode)
    return proc.stdout.splitlines()


def barcode_pass(text):
    barcode = code128.svg(text, height=80, thickness=1)
    barcode_64 = b64encode(barcode.encode('utf-8'))
    return barcode_64.decode()


def handle_args():
    parser = argparse.ArgumentParser(description='Shame sheet generator')
    parser.add_argument('-L', '--lenovo', action='store_true', help="Create a password that is safe for lenovo bios")
    parser.add_argument('-S', '--sheetcount', help="Number of assets requested, increasing sequentially from asset entered")
    parser.add_argument('assets', nargs='+', help='List of asset IDs to create shame for')
    parser.add_argument('-P', '--password', help='optional cli specified user password')
    args = parser.parse_args()
    return args


def fill_assets(count, base_asset):
    if len(base_asset) > 1:
        bail("Too many assets, only list one when using -S", 1)
    start = int(base_asset[0]) + 1
    end = int(base_asset[0]) + int(count)
    for i in range(start, end):
        base_asset.append(str(i))


def get_jinja_env():
    return Environment(loader=FileSystemLoader(TEMPLATE_DIR)).get_template(USE_TEMPLATE)


def write_pdf(text, path):
    HTML(string=text, base_url=TEMPLATE_DIR).write_pdf(path)


def upload_ops(search_path, auth_token):
    with Session() as sesh:
        sesh.headers['Content-Type'] = 'application/octet-stream'
        sesh.headers['Authorization'] = 'Bearer {}'.format(auth_token)
        upload_params = {'uploadType': 'media'}
        for gpg_file in [i for i in os.listdir(search_path) if 'gpg' in i]:
            upload_params['name'] = gpg_file
            with open(os.path.join(search_path, gpg_file), 'rb') as file_bytes:
                print('Uploading {} ...'.format(gpg_file))
                try:
                    r = sesh.post(UPLOAD_ENDPOINT, data=file_bytes.read(), params=upload_params)
                    r.raise_for_status()
                except HTTPError as err:
                    print(err)
                    print('ERROR: Failed to upload {}. It is located in {}. You must upload it manually to gs://{}'.format(gpg_file, search_path, OPS_BUCKET))


def main():
    args = handle_args()
    if args.sheetcount is not None:
        fill_assets(args.sheetcount, args.assets)
    auth_token = cmd_runner('gcloud auth print-access-token')[0]
    bios_chars = string.ascii_letters + string.digits
    tmpdir = mkdtemp()
    template = get_jinja_env()
    template_vars = {'dstamp': TODAY.strftime('%Y-%m-%d')}
    it_group = ' '.join(cmd_runner('bash -c get_it_group'))
    print('Storing shame sheets in {}'.format(tmpdir))
    for asset in args.assets:
        pdf_path = os.path.join(tmpdir, SHAME_SHEET.format(asset))
        ops_path = os.path.join(tmpdir, OPS_KEY.format(asset))
        if args.lenovo:
            print('Generating BIOS Safe Passwords for {}'.format(asset))
            ops_pass = ai_mkpass('bios', char_set=bios_chars)
            user_pass = ai_mkpass('bios', char_set=bios_chars)
        else:
            print('Generating user and ops Passwords for {}'.format(asset))
            ops_pass = ai_mkpass('temp')
            user_pass = args.password if args.password else ai_mkpass('temp')
        user_barcode = barcode_pass(user_pass)
        ops_barcode = barcode_pass(ops_pass)
        template_vars['asset'] = asset
        template_vars['password'] = user_pass
        template_vars['ops_pass'] = ops_pass
        template_vars['user_barcode'] = user_barcode
        template_vars['ops_barcode'] = ops_barcode
        write_pdf(template.render(template_vars), pdf_path)
        cmd_runner('gpg --trust-model always -e -o {} {}'.format(ops_path, it_group), ops_pass)
    upload_ops(tmpdir, auth_token)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

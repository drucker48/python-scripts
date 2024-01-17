#!/usr/bin/env python3
# Automated provisioning of a software development workstation.
# Depends on a Ubuntu 22.04 LTS base setup with IT's eng autoinstall.
#
from __future__ import annotations

import argparse
import getpass
import json
import logging.handlers
import os
import pathlib
import secrets
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import gnupg
import pexpect
import requests
from requests import HTTPError, Session

UBUNTU_22 = "22.04"
LOGGER = logging.getLogger("linuxbootstrap")
GPG = gnupg.GPG()
DEFAULT_SECRET = "changeme"
LOCALDIR = "/opt/company"
TEMPDIR = tempfile.mkdtemp()
OPS_KEY = "{}-ops_login.txt.gpg"
OPS_BUCKET = "company-bucket"
REMOTE_PATH = "0000-2204-deployment"
UPLOAD_ENDPOINT = f"https://www.googleapis.com/upload/storage/v1/b/{OPS_BUCKET}/o"
QUERY_ENDPOINT = f"https://storage.cloud.google.com/{OPS_BUCKET}"
FINAL_SLEEP_SECS = 10

LUKS_NOT_REQUIRED_SYSTEMS = []
with open("/opt/company/unencrypted_allow_list.txt", "r") as allow_list:
    for model_name in [line.strip() for line in allow_list.readlines()]:
        if model_name and not model_name.startswith("#"):
            LUKS_NOT_REQUIRED_SYSTEMS.append(model_name)


class NoLUKSError(Exception):
    pass


def setup_logger():
    """Set up logger"""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filename="/var/log/linuxbootstrap.log",
    )


def check_root():
    """check if the command is executed as root"""
    if not os.geteuid() == 0:
        return False
    else:
        return True


def cmd_runner(cmd, inp=None):
    proc = subprocess.run(
        cmd.split(),
        capture_output=True,
        text=True,
        check=True,
        input=inp,
    )
    return proc.stdout.splitlines()


def is_running_valid_ubuntu_version():
    """
    check for valid Ubuntu version
    Returns: Boolean Values

    """
    release = subprocess.run(
        ["/usr/bin/lsb_release", "-rs"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip()
    if release == UBUNTU_22:
        print("OS compatibility check is done")
        LOGGER.info("OS compatibility check is done")
        return True
    print("Incompatible OS Version")
    LOGGER.fatal(f"incompatible OS version {release}")
    return False


def password_validate(password):
    """
    Enforce password complexity

    """
    val = True

    if len(password) < 14:
        print("password length should be at least 14 characters")
        LOGGER.info("Password length should be at least 14 characters.")
        val = False

    if len(password) > 30:
        print("length should be not be greater than 30")
        val = False

    if not any(char.isdigit() for char in password):
        print("Password should have at least one numeral")
        LOGGER.info("Password should have at least one numeral.")
        val = False

    if not any(char.isupper() for char in password):
        print("Password should have at least one uppercase letter")
        LOGGER.info("Password should have at least one uppercase letter.")
        val = False

    if not any(char.islower() for char in password):
        print("Password should have at least one lowercase letter")
        LOGGER.info("Password should have at least one lowercase letter.")
        val = False

    if not any(char in string.punctuation for char in password):
        print("Password should have at least one of the special characters")
        LOGGER.info("Password should have at least one of the special characters.")
        val = False
    if val:
        return val


def luks_required():
    """
    Is an encrypted filesystem requireed for this system
    determine by system-product-name system-family or chassis-type
    """
    output = subprocess.run(
        ["/usr/sbin/dmidecode", "-s", "system-product-name"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip()
    return not output in LUKS_NOT_REQUIRED_SYSTEMS


def set_luks_user_pass():
    """
    Set user Luks password

    """
    print(
        "Note: The local user's account password should have a minimum of 14 characters "
        "containing at least one number, "
        "one uppercase, one lowercase and one special character.",
    )
    while True:
        luks_password = getpass.getpass(prompt="Enter the user's local account password: ")
        reenter_luks_password = getpass.getpass(prompt="Reenter user's local account password: ")
        if password_validate(luks_password) and luks_password == reenter_luks_password:
            print("Password validated successfully")
            LOGGER.info("Password validated successfully.")
            return luks_password
        else:
            print("Password didn't match. Please re-enter the password")
            LOGGER.info("Password didn't match.")


def check_network_connection():
    """
    check for Network connection
    Returns: Boolean Value

    """
    try:
        urllib.request.urlopen("https://www.google.com")
        return True
    except urllib.error.URLError as error:
        print("Please check your internet connection and rerun the command.")
        LOGGER.exception(f"No internet connection {error}")
        return False


def mk_pass():
    """
    Generate a random 25 character password with at least one upper, lower, digit, and special char

    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    while True:
        password = "".join(secrets.choice(alphabet) for i in range(25))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in string.punctuation for c in password)
        ):
            break
    return password


def get_encrypted_disk():
    """
    Get encrypted disk

    Returns: Encrypted disk like sda3 or sda5
    Raises NoLUKSError on no encrypted filesystem found

    """
    output_lines = subprocess.run(
        ["dmsetup", "status"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split(" \n")
    try:
        encrypted_vols = [vol.split(":")[0] for vol in output_lines if vol.endswith("crypt")]
        encrypted_vol = encrypted_vols[0]
    except IndexError:
        LOGGER.warning("No encrypted devices found")
        raise NoLUKSError()
    output_lines = subprocess.run(
        ["cryptsetup", "status", encrypted_vol],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    encrypted_disk = [
        line.split(":")[1].strip() for line in output_lines if line.startswith("  device:  ")
    ][0]
    LOGGER.info(f"Encrypted disk is {encrypted_disk}")
    return encrypted_disk


def is_virtual_machine():
    """
    Check if the machine is Virtual Machine
    """
    virtual_machine_tags = ["VMware, Inc."]
    try:
        output = subprocess.run(
            ["/usr/sbin/dmidecode", "-s", "system-manufacturer"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.rstrip()
        if output in virtual_machine_tags:
            LOGGER.info(" Machine is a virtual machine")
            return True
        else:
            return False
    except Exception as error:
        print(str(error))
        return False


def get_serial_number():
    """
    Get model number of the machine

    Returns: Model of the machine
    """
    try:
        output = subprocess.run(
            ["/usr/sbin/dmidecode", "-s", "system-serial-number"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.rstrip()
        if is_virtual_machine():
            special_characters = [",", "*", ":", ";", " "]
            modelnumber = "".join(filter(lambda i: i not in special_characters, output))
            LOGGER.info(f"Model number is {modelnumber}")
            return str(modelnumber)
        # modelnumber = output.split(" ")[1:][0]
        LOGGER.info(f"Serial number is {output}")
        return str(output)
    except subprocess.CalledProcessError as error:
        LOGGER.error(error)
        print(str(error))
        sys.exit(1)


SECRETS_FILE = f"itops-{get_serial_number()}.txt"
SECRETS_PATH = f"{TEMPDIR}/{SECRETS_FILE}"
ENCRYPTED_SECRETS_FILE = f"{SECRETS_FILE}.gpg"
ENCRYPTED_SECRETS_PATH = f"{LOCALDIR}/{ENCRYPTED_SECRETS_FILE}"

RANDOM_PASSWORD = mk_pass()

# for testing purpose
# RANDOM_PASSWORD = "luks1234"


def store_itops_password():
    """
    Store itops account password in file

    """
    with open(SECRETS_PATH, "a", encoding="utf-8") as f:
        f.write(f"{RANDOM_PASSWORD}\n")
    LOGGER.info(f"File password is written to {SECRETS_PATH}")


def store_luks_key():
    output_lines = subprocess.run(
        ["dmsetup", "table", "--showkeys"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    with open(SECRETS_PATH, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(output_lines)
        f.write("\n")
    LOGGER.info(f"LUKS key is written to {SECRETS_PATH}")


def change_itops_password():
    """
    Change default itoperations account password

    """
    child = pexpect.spawn("/usr/bin/passwd itops")
    child.expect("New password:")
    child.sendline(RANDOM_PASSWORD)
    child.expect("Retype new password:")
    child.sendline(RANDOM_PASSWORD)
    child.expect(pexpect.EOF)
    LOGGER.info("Randomized itops password")


def validate_default_luks_password():
    """
    Validate default LUKS password

    """
    try:
        encrypted_device = get_encrypted_disk()
        child = pexpect.spawn("cryptsetup luksOpen --test-passphrase " + encrypted_device)
        child.expect("Enter passphrase for " + encrypted_device + ":")
        child.sendline(DEFAULT_SECRET)
        child.expect(pexpect.EOF)
        output = child.before
        output = output.decode("utf-8")
        return True
    except pexpect.TIMEOUT as error:
        LOGGER.critical(f"Error validating the Default Password {error}")
        return False


def set_itops_luks_passwd():
    """
    Set LUKS password for keyslot0

    """
    if validate_default_luks_password():
        print("Disk encryption is set to default password; will set to randomized itops password")
        try:
            encrypted_device = get_encrypted_disk()
            child = pexpect.spawn("cryptsetup luksChangeKey " + encrypted_device + " --key-slot 0")
            child.expect("Enter passphrase to be changed:")
            child.sendline(DEFAULT_SECRET)
            child.expect("Enter new passphrase:")
            child.sendline(RANDOM_PASSWORD)
            child.expect("Verify passphrase:")
            child.sendline(RANDOM_PASSWORD)
            child.expect(pexpect.EOF)
            LOGGER.info("LUKS password set for Keyslot0")
        except pexpect.TIMEOUT as error:
            LOGGER.critical(f"Error with changing the password {error}")
    else:
        print(
            "Disk encryption is not using the default password; assuming already set with new password",
        )


def is_keyslot1_enabled():
    """
    Check if keyslot1 is enabled

    """
    encrypted_disk = get_encrypted_disk()
    if not isinstance(encrypted_disk, str):
        LOGGER.critical("Unable to find encrypted drive")
        sys.exit(1)

    output = json.loads(
        subprocess.run(
            ["cryptsetup", "luksDump", encrypted_disk, "--dump-json-metadata"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout,
    )
    if output.get("keyslots", {}).get("1", {}):
        LOGGER.info("Key Slot 1 is enabled")
        return True

    LOGGER.info("Key Slot 1 is disabled")
    return False


def set_user_luks():
    """
    Set user password for keyslot1

    """
    if not is_keyslot1_enabled():
        print("Setting up LUKS password for the user")
        try:
            user_luks_password = set_luks_user_pass()
            encrypted_device = get_encrypted_disk()
            child = pexpect.spawn(f"cryptsetup luksAddKey {encrypted_device} --key-slot 1")
            child.expect("Enter any existing passphrase:")
            child.sendline(DEFAULT_SECRET)
            child.expect("Enter new passphrase for key slot:")
            child.sendline(user_luks_password)
            child.expect("Verify passphrase:")
            child.sendline(user_luks_password)
            child.expect(pexpect.EOF)
        except pexpect.TIMEOUT as error:
            LOGGER.critical(f"Error with changing the password {error}")
    else:
        print("Key Slot 1 is enabled with the local account Password")


def get_ai_encrypt_keyring():
    """
    Download GPG key

    """
    asc_text = requests.get(
        "https://storage.googleapis.com/ai-encrypt/ascii_keyring",
        timeout=5,
    ).text
    GPG.import_keys(asc_text)


def get_control_group():
    """
    Get control group

    """
    response = requests.get(
        "https://storage.googleapis.com/company-bucket/control-group",
        timeout=5,
    ).text.splitlines()
    it_keys = []
    for email in response:
        it_keys.append(email.strip().split()[0])
    return it_keys


def get_it_group():
    """
    get it group

    """
    response = requests.get(
        "https://storage.googleapis.com/cloud-bucket/it-group",
        timeout=5,
    ).text.splitlines()
    ops_keys = []
    for email in response:
        ops_keys.append(email.strip().split()[0])
    return ops_keys


def create_gpg_file():
    """
    Create GPG file

    """
    ops_keys = get_it_group()
    control_keys = get_control_group()
    with open(SECRETS_PATH, "rb") as f:
        status = GPG.encrypt_file(
            f,
            recipients=ops_keys + control_keys,
            output=ENCRYPTED_SECRETS_PATH,
            always_trust=True,
        )
        LOGGER.info(f"ok: {status.ok}")
        LOGGER.info(f"status: {status}")
        LOGGER.info(f"stderr: {status.stderr}")
        if not status.ok:
            raise Exception(f"GPG encryption failed: {status.stderr}")


def start_gcloud_authentication():
    """
    Gcloud authentication to upload LUKS headers and itoperations account password

    """
    print("Initiating Google Cloud Auth")
    subprocess.run(["/usr/bin/gcloud", "auth", "login"], check=True)


def upload_password():
    """
    Upload password and LUKS headers to the GCP bucket
    """
    auth_token = cmd_runner("gcloud auth print-access-token")[0]
    with Session() as sesh:
        sesh.headers["Content-Type"] = "application/octet-stream"
        sesh.headers["Authorization"] = f"Bearer {auth_token}"
        upload_params = {"uploadType": "media"}
        upload_params["name"] = requests.utils.quote(f"{REMOTE_PATH}/{ENCRYPTED_SECRETS_FILE}")
        with open(ENCRYPTED_SECRETS_PATH, "rb") as file_bytes:
            print(f"Uploading {ENCRYPTED_SECRETS_PATH} ...")
            try:
                r = sesh.post(UPLOAD_ENDPOINT, data=file_bytes.read(), params=upload_params)
                r.raise_for_status()
            except HTTPError:
                print(
                    f"ERROR: Failed to upload {ENCRYPTED_SECRETS_PATH}. "
                    f"You must upload it manually to gs://{OPS_BUCKET}/{REMOTE_PATH}",
                )
                raise


def verify_upload_and_remove():
    """
    Verify if LUKS headers and ITOPS passwords uploaded and remove if so
    """
    auth_token = cmd_runner("gcloud auth print-access-token")[0]
    with Session() as sesh:
        sesh.headers["Content-Type"] = "application/octet-stream"
        sesh.headers["Authorization"] = f"Bearer {auth_token}"
        query_endpoint = f"{QUERY_ENDPOINT}/{REMOTE_PATH}/{ENCRYPTED_SECRETS_FILE}"
        try:
            response = sesh.get(query_endpoint)
            response.raise_for_status()
            print(f"{ENCRYPTED_SECRETS_FILE} uploaded successfully")
            LOGGER.info(f"{ENCRYPTED_SECRETS_FILE} uploaded successfully")
            # TODO: verify contents of uploaded file vs source
            # remove the local copies
            pathlib.Path(SECRETS_PATH).unlink(missing_ok=True)
            pathlib.Path(ENCRYPTED_SECRETS_PATH).unlink(missing_ok=True)
        except HTTPError:
            LOGGER.error(
                f"unable to verify gs://{OPS_BUCKET}/{REMOTE_PATH}/{ENCRYPTED_SECRETS_FILE} : {response}",
            )
            print(
                f"ERROR: Failed to verify that {ENCRYPTED_SECRETS_FILE} was uploaded. "
                f"Please verify it manually in gs://{OPS_BUCKET}/{REMOTE_PATH} "
                f"and remove {ENCRYPTED_SECRETS_PATH}.",
            )
            raise


def linux_deploy():
    """
    Run the deploy shell script
    """
    subprocess.run(["/opt/company/linux-deploy.sh"], check=True)


def switch_nvidia():
    """Switch to nvidia for graphics"""
    subprocess.run(
        ["/usr/bin/prime-select", "nvidia"],
        capture_output=True,
        text=True,
        check=False,
    )


def enable_bios_update():
    """Schedules a bios update for the next reboot"""
    print("Scheduling any bios updates for next reboot")
    # dont check output since if there's no updates, retval is nonzero
    subprocess.run(
        ["/usr/bin/fwupdmgr", "refresh"],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["/usr/bin/fwupdmgr", "-y", "--offline", "update"],
        capture_output=True,
        text=True,
        check=False,
    )


def reboot_machine():
    """Reboots the machine"""
    print(f"System will reboot after {FINAL_SLEEP_SECS}")
    time.sleep(FINAL_SLEEP_SECS)
    LOGGER.info("Rebooting")
    subprocess.run(
        ["/sbin/reboot"],
        check=True,
    )


def bootstrap():
    """
    Bootstrap the machine by executing the functions

    """
    if is_running_valid_ubuntu_version() and check_network_connection():
        switch_nvidia()
        linux_deploy()
        store_itops_password()
        try:
            store_luks_key()
            set_user_luks()
            set_itops_luks_passwd()
        except NoLUKSError:
            if luks_required():
                LOGGER.fatal(
                    "Your Machine's Product is NOT in the allowed list"
                    "Please reach out to the ITS Team for the correct installer to continue with the Ubuntu 22.04 installation"
                )
                sys.exit(1)
        get_ai_encrypt_keyring()
        create_gpg_file()
        start_gcloud_authentication()
        upload_password()
        verify_upload_and_remove()
        change_itops_password()
        enable_bios_update()
        reboot_machine()
    else:
        print("Bootstrap process is exiting")
        sys.exit(1)


def main():
    """
    Takes argument and runs the command

    """
    parser = argparse.ArgumentParser(description="Bootstrap Linux Machine")
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument(
        "--bootstrap",
        default=None,
        action="store_true",
        help="Bootstrap New Linux client",
    )
    command.add_argument(
        "--linuxdeploy",
        default=None,
        action="store_true",
        help="Rerun linuxdeploy",
    )
    command.add_argument(
        "--gcpupload",
        default=None,
        action="store_true",
        help="Upload password to the GCP",
    )
    command.add_argument("--version", action="version", version=f"{parser.prog} version 1.0.0")
    args = parser.parse_args()
    if not check_root():
        print("This tool must be run as root!")
        return 1
    setup_logger()

    if args.bootstrap:
        bootstrap()
    elif args.linuxdeploy:
        linux_deploy()
    elif args.gcpupload:
        upload_password()
        verify_upload_and_remove()
    else:
        print("Invalid Arguments")


if __name__ == "__main__":
    main()

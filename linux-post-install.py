#!/usr/bin/env python3

# Automated provisioning of a software development workstation.
# Depends on a Ubuntu 22.04 LTS base setup with autoinstall.


import argparse
import logging.handlers
import os
import subprocess
import sys
import tempfile

# Installed with the ISO image
import gnupg
import requests

SLACK_VERSION = "4.33.73"
VPN_VERSION = "6.1.1.0-49"
NVIDIA_MAJOR_VERSION = 535
INSTALLER_BUCKET = "https://storage.googleapis.com/ai-images/Ubuntu-Installer-Files"
TEMP_DIR = tempfile.mkdtemp()
LOGGER = logging.getLogger("linux-post-install")
GPG = gnupg.GPG()
KEYRING_DIR = "/usr/share/keyrings"
SOURCES_DIR = "/etc/apt/sources.list.d"


PKGS_TO_INSTALL = [
    "bazel",
    "chrome-gnome-shell",
    # nvidia files needed to make GL apps work plus `prime-select nvidia` in clientctl
    # see also the `prime-select nvidia` in clientctl
    f"libnvidia-decode-{NVIDIA_MAJOR_VERSION}",
    f"libnvidia-encode-{NVIDIA_MAJOR_VERSION}",
    f"libnvidia-gl-{NVIDIA_MAJOR_VERSION}",
    f"linux-modules-nvidia-{NVIDIA_MAJOR_VERSION}-generic-hwe-22.04",
    "nvidia-cuda-toolkit",
    "nvidia-prime",
    "nvidia-settings",
    f"nvidia-utils-{NVIDIA_MAJOR_VERSION}",
    f"xserver-xorg-video-nvidia-{NVIDIA_MAJOR_VERSION}",
    "mesa-utils",
    ### End of nvidia stuff ###
    "code",
    # ensure the updater GUI tool works
    "gnome-software-plugin-snap", 
    "tpm2-openssl",
    "tpm2-tools",
    f"{TEMP_DIR}/google-chrome-stable_current_amd64.deb",
    f"{TEMP_DIR}/slack-desktop-{SLACK_VERSION}-amd64.deb",
    f"{TEMP_DIR}/GlobalProtect_UI_focal_deb-{VPN_VERSION}.deb",
]

# Confirm network connectivity
def check_network_connection():
    """
    Check for Network connection
    Returns: Boolean Value

    """
    try:
        res = requests.get("https://www.google.com")
        res.raise_for_status()
        return True
    except (
        requests.HTTPError,
        requests.ConnectionError,
        requests.Timeout,
        requests.TooManyRedirects,
    ):
        LOGGER.error("Please check your internet connection and rerun the command.")
        return False

def check_root():
    """check if being executed as root"""
    return os.geteuid() == 0


def setup_logger():
    logging.basicConfig(
        filename="/var/log/linux-post-install.log",
        level=logging.DEBUG,
        filemode="w",
        datefmt="%Y-%m-%d %H:%M:%S",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))

# Configure shell commands and return output function
def run_command(command, inp=None):
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            input=inp,
            text=True,
            capture_output=True,
        )
        LOGGER.info(f"Command executed successfuly: {command}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"Error executing command: {command}\nError message: {e.stderr}")

def get_bazel_key():
        
        destination_path = os.path.join(KEYRING_DIR, 'bazel.gpg')

        response = requests.get("https://bazel.build/bazel-release.pub.gpg", timeout=5)
        response.raise_for_status()

        with open(destination_path, 'wb') as bazel_gpg:
            bazel_gpg.write(response.content)
            os.chmod("/usr/share/keyrings/bazel.gpg", 0o444)
            LOGGER.info("Bazel GPG successfully downloaded")
        
def config_repo_bazel():
        """
        Configure Bazel repo
        """
        with open(f"{KEYRING_DIR}/bazel.gpg", "rb") as bazel_key_file:
            bazel_key_data = bazel_key_file.read()
            GPG.import_keys(bazel_key_data)
            LOGGER.info("Bazel key imported.")
        with open(f"{SOURCES_DIR}/bazel.list", "w") as bazel_source:
            bazel_source.write(
             "deb [signed-by=/usr/share/keyrings/bazel.gpg] https://storage.googleapis.com/bazel-apt stable jdk1.8"
        )

def get_docker_key():
        
        destination_path = os.path.join(KEYRING_DIR, 'docker.gpg')

        response = requests.get("https://download.docker.com/linux/ubuntu/gpg", timeout=5)
        response.raise_for_status

        with open(destination_path, 'wb') as docker_gpg:
            docker_gpg.write(response.content)
    
def config_repo_docker():
        
        with open(f"{KEYRING_DIR}/docker.gpg", "rb") as docker_key_file:
            docker_key_data = docker_key_file.read()
            GPG.import_keys(docker_key_data)
            os.chmod("/usr/share/keyrings/docker.gpg", 0o444)
            LOGGER.info("Docker key imported.")
            #Config sources.list file for docker repo
        with open(f"{SOURCES_DIR}/docker.list", "w") as docker_source:
            docker_source.write(
            "deb [signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable"
        )

def get_nvidia_container():
        
        destination_path = os.path.join(KEYRING_DIR, 'nvidia-container-toolkit.gpg')

        response = requests.get(
                "https://nvidia.github.io/libnvidia-container/gpgkey", timeout=5
            )
        response.raise_for_status()
        with open (destination_path, 'wb') as nvidia_gpg:
            nvidia_gpg.write(response.content) 
    
def config_repo_nvidia():
        
        with open(f"{KEYRING_DIR}/nvidia-container-toolkit.gpg", "rb") as nvidia_key_file:
            nvidia_key_data = nvidia_key_file.read()
            GPG.import_keys(nvidia_key_data)
            os.chmod("/usr/share/keyrings/nvidia-container-toolkit.gpg", 0o444)
            LOGGER.info("nvidia-container-toolkit key imported.")
            #Create sources.list file for nvidia 
        with open(f"{SOURCES_DIR}/nvidia-container-toolkit.list", "w") as nvidia_source:
            nvidia_source.write(
            "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://nvidia.github.io/libnvidia-container/stable/ubuntu18.04/$(ARCH) /"
        )

def get_vscode():
        
        destination_path = os.path.join(KEYRING_DIR, 'vscode.gpg')

        response = requests.get(
            "https://packages.microsoft.com/keys/microsoft.asc",
            timeout=5
            )
        response.raise_for_status()

        with open (destination_path, 'wb') as vscode_gpg:
            vscode_gpg.write(response.content)
            LOGGER.info("Downloaded vscode.gpg file to the keychain dir.")     

def config_repo_vscode():
            
        with open(f"{KEYRING_DIR}/vscode.gpg", "rb") as vscode_key_file:
            vscode_key_data = vscode_key_file.read()
            GPG.import_keys(vscode_key_data)
            os.chmod("/usr/share/keyrings/vscode.gpg", 0o444)
            LOGGER.info("Imported vscode key.")
            # Config sources.list file for vscode
        with open(f"{SOURCES_DIR}/vscode.list", "w") as vscode_source:
            vscode_source.write(
                "deb [signed-by=/usr/share/keyrings/vscode.gpg] https://packages.microsoft.com/repos/code stable main"
            )

def config_repos():
    get_bazel_key()
    config_repo_bazel()
    get_docker_key()
    config_repo_docker()
    get_nvidia_container()
    config_repo_nvidia()
    get_vscode()
    config_repo_vscode()

def download_packages():
    
    urls_to_download = [
    "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
    f"{INSTALLER_BUCKET}/GlobalProtect_UI_focal_deb-{VPN_VERSION}.deb",
    f"{INSTALLER_BUCKET}/slack-desktop-{SLACK_VERSION}-amd64.deb",
    ]

    for url in urls_to_download:

        filename = url.split('/')[-1]
        destination_path = os.path.join(TEMP_DIR, filename)
                
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(destination_path, 'wb') as deb_files:
            deb_files.write(response.content)
            os.chmod(destination_path, 0o444)
            LOGGER.info(f"Downloaded {filename} to {destination_path}")
    
def run_mipi_commands():
    """
    Installing support for Intel MIPI cameras
    """
    apt_commands = [
        # support Dell 5680 cameras https://wiki.ubuntu.com/IntelMIPICamera
        # TODO: remove when ubuntu supports
        f"apt-get -y install linux-oem-22.04c linux-headers-oem-22.04c linux-modules-nvidia-{NVIDIA_MAJOR_VERSION}-oem-22.04c",
        f"apt-get -y purge linux-generic-hwe-22.04 linux-image-generic-hwe-22.04 linux-modules-nvidia-{NVIDIA_MAJOR_VERSION}-generic-hwe-22.04 linux-headers-generic-hwe-22.04",
        "add-apt-repository ppa:oem-solutions-engineers/oem-projects-meta",
        "apt-get update",
        "apt-get -y install oem-somerville-muk-meta",
        "apt-get update",
        "apt-get -y dist-upgrade",
        "apt-get -y install libcamhal-ipu6ep0",
    ]
    for command in apt_commands:
        run_command(command)

def install_packages():
    run_command("update-ca-certificates")
    
    config_repos()
    
    docker_lines = [
        "Explanation: work around bug in aurora-engineering-* https://go/jira/AV-247331",
        "Package: docker-ce*",
        "Pin: version 5:24.*",
        "Pin-Priority: 1001"
    ]
    
    with open("/etc/apt/preferences.d/docker.pref", "w") as docker_pref:
        docker_pref.writelines("\n".join(docker_lines))

    run_command("apt-get update")

    for packages in PKGS_TO_INSTALL:
        run_command(f'apt-get -y --no-install-recommends --allow-downgrades install {packages}')

    apt_commands = [
        "apt-get update",
        "apt-get -y dist-upgrade",
        "apt-get -y autoremove --purge",
    ]
    
    for commands in apt_commands:
        run_command(commands)
    
    if run_command("dmidecode -s system-product-name") == "Precision 5680":
        run_mipi_commands()
        LOGGER.info("MIPI camera setup successfully for Dell 5680.")

def postconfig_chrome():
    # per https://confluence.int.aurora.tech/display/IS/Linux+Chrome+Management
    os.makedirs("/etc/opt/chrome/policies/enrollment", exist_ok=True)
    os.chmod("/etc/opt/chrome/policies/enrollment/", 0o755)
    with open(
        "/etc/opt/chrome/policies/enrollment/CloudManagementEnrollmentToken", "w"
     ) as chrome_enroll:
        chrome_enroll.write("bed58b3e-980f-4ec8-8e26-efb676d0466b")
        # install gnome-shell-intergration
        install_chrome_extension()

def install_chrome_extension():
    pref_file = "gphhapmejobijbbhgpjhcjognlahblep.json"
    upd_url = "https://clients2.google.com/service/update2/crx"

    os.makedirs("/opt/google/chrome/extensions", exist_ok=True)
    # Config Chrome extension .json file 
    chrome_ext_file = [
                '{',
                f'"external_update_url": "{upd_url}"',
                '}'
            ]
    with open(f"/opt/google/chrome/extensions/{pref_file}", "w") as chrome_ext:
        chrome_ext.writelines("\n".join(chrome_ext_file))

def postconfig_pam_password():
    config_lines = [
    "retry=3",
    "minlen=13",
    "lcredit=-1",                                                                                                                                                               
    "ucredit=-1",
    "dcredit=-1",
    "ocredit=-1",
    "enforce_for_root"
   ]
    with open("/etc/security/pwquality.conf", "w") as pam_config:
        pam_config.writelines("\n".join(config_lines))

def edit_grub_file():
    # Get machine to auto boot to the Grub menu for 10 seconds
    # Will assist in troubleshooting efforts by making it easier
    # to access recovery on specs using UEFI
    GRUB_FILE = "/etc/default/grub"
    with open(GRUB_FILE, "r") as grub_edit:
        lines = grub_edit.readlines()
        for line in lines:
            if f"GRUB_TIMEOUT_STYLE=hidden" in line:
                run_command("sed -i -e 's/^GRUB_TIMEOUTSTYLE=hidden/#&/' /etc/default/grub")
            elif f"GRUB_TIMEOUT=0" in line:
                run_command("sed -i -e 's/^GRUB_TIMEOUT=/GRUB_TIMEOUT=10/' /etc/default/grub")
    
        
def final_settings():
    run_command("sed -i -e 's/Prompt=lts/Prompt=never/' /etc/update-manager/release-upgrades")
    postconfig_chrome()
    postconfig_pam_password()
    edit_grub_file()
    run_command("update-grub")

    # Set system-wide favorites
    with open("/etc/dconf/profile/user", "w") as user_profile:
        user_profile.write("user-db:user\nsystem-db:local")
    os.makedirs("/etc/dconf/db/local.d", exist_ok=True)
    
    with open("/etc/dconf/db/local.d/00-favorite-apps", "w") as fav_apps:
        fav_apps.write(
            "[org/gnome/shell]\nfavorite-apps = ['slack.desktop', 'google-chrome.desktop', 'code.desktop', 'org.gnome.Terminal.desktop']"
        )
    run_command("dconf update")
    run_command("systemctl disable systemd-networkd-wait-online.service")

def run_post_install():
    """
    Complete ISO install by running script functions
    """
    download_packages()
    install_packages()
    final_settings()
    LOGGER.info("Post-install script is finished.")

def main():
    """
    arguments to run individual command
    """
    parser = argparse.ArgumentParser(description="Bootstrap Linux Machine")
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument(
        "--post-install",
        default=None,
        action="store_true",
        help="Rerun linux-post-install",
    )
    command.add_argument(
        "--download-pkgs",
        default=None,
        action="store_true",
        help="Rerun packages download function",
    )
    command.add_argument(
        "--install-pkgs",
        default=None,
        action="store_true",
        help="Re-run packages install function",
    )
    command.add_argument("--version", action="version", version=f"{parser.prog} version 1.1.0")
    args = parser.parse_args()
    try:
        if not check_root():
            sys.exit("This tool must be run as root")
        if not check_network_connection():
            sys.exit("This tool requires internet access")
        setup_logger()
        if args.post_install:
            run_post_install()
        elif args.download_pkgs:
            download_packages()
        elif args.install_pkgs:
            install_packages()
        else:
            print("Invalid Arguments")
    except (
        OSError,
        FileNotFoundError,
        PermissionError,
        requests.ConnectionError,
        requests.Timeout,
        requests.HTTPError,
        requests.TooManyRedirects
    ) as e:
        LOGGER.error(f"Error caught during execution: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

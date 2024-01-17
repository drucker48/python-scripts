import subprocess
import time
from gi.repository import Notify

def get_ubuntu_version():
    try:
        cmd = ["lsb_release", "-r", "-s"]
        version = subprocess.check_output(cmd).decode().strip()
        return version
    except:
        return None

def send_notification(message):
    Notify.init("Ubuntu Version Checker")
    notification = Notify.Notification.new("Ubuntu Version Alert", message)
    notification.show()

def check_ubuntu_version():
    current_version = get_ubuntu_version()
    if current_version is None:
        send_notification("Failed to determine Ubuntu version.")
    else:
        latest_version = "22.04"
        if current_version < latest_version:
            message = f"Your Ubuntu version ({current_version}) is outdated. Please upgrade to the latest version ({latest_version})."
            send_notification(message)

def main():
    while True:
        check_ubuntu_version()
        time.sleep(1800)  # Sleep for 30 minutes (30 * 60 seconds)

if __name__ == "__main__":
    main()

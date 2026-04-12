import json
import os

BASE_DIR = os.path.expanduser("~/macVMs")
VM_DIR = os.path.join(BASE_DIR, "vms")
ISO_DIR = os.path.join(BASE_DIR, "isos")

os.makedirs(VM_DIR, exist_ok=True)
os.makedirs(ISO_DIR, exist_ok=True)

ISOS = {
    "debian": {
        "url": "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso",
        "file": os.path.join(ISO_DIR, "debian.iso"),
        "boot": {
            "kernel_candidates": [
                "install.amd/vmlinuz",
            ],
            "initrd_candidates": [
                "install.amd/initrd.gz",
            ],
            "append": [
                "console=tty0",
                "console=ttyS0,115200n8",
                "vga=off",
                "DEBIAN_FRONTEND=text",
                "---",
            ],
        },
    },
    "ubuntu": {
        "url": "https://ubuntu.mirror.garr.it/releases/24.04.4/ubuntu-24.04.4-live-server-amd64.iso",
        "file": os.path.join(ISO_DIR, "ubuntu.iso"),
        "boot": {
            "kernel_candidates": [
                "casper/vmlinuz",
                "casper/hwe-vmlinuz",
            ],
            "initrd_candidates": [
                "casper/initrd",
                "casper/initrd.gz",
                "casper/hwe-initrd",
            ],
            "append": [
                "console=tty0",
                "console=ttyS0,115200n8",
                "quiet",
                "loglevel=3",
                "printk.time=0",
                "systemd.show_status=auto",
                "---",
            ],
        },
    },
}

DEBIAN_PRESEED_TEMPLATE = """d-i debian-installer/locale string en_US
d-i keyboard-configuration/xkb-keymap select us
d-i netcfg/choose_interface select auto
d-i finish-install/keep-consoles boolean true
d-i debian-installer/add-kernel-opts string console=tty0 console=ttyS0,115200n8

d-i clock-setup/utc boolean true
d-i time/zone string UTC

d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true

tasksel tasksel/first multiselect standard
d-i pkgsel/include string

d-i grub-installer/only_debian boolean true

d-i preseed/late_command string mkdir -p /target/etc/default/grub.d; printf 'GRUB_TIMEOUT=5\\nGRUB_TIMEOUT_STYLE=menu\\nGRUB_TERMINAL_INPUT="console serial"\\nGRUB_TERMINAL_OUTPUT="console serial"\\nGRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"\\nGRUB_CMDLINE_LINUX_DEFAULT=""\\nGRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"\\n' > /target/etc/default/grub.d/serial.cfg; in-target systemctl enable serial-getty@ttyS0.service; in-target update-grub{shared_late_command}

d-i finish-install/reboot_in_progress note
"""


def vm_path(name):
    return os.path.join(VM_DIR, name)


def config_path(name):
    return os.path.join(vm_path(name), "config.json")


def load_config(name):
    with open(config_path(name), "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(name, data):
    with open(config_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def seed_dir(name):
    return os.path.join(vm_path(name), "seed")


def boot_cache_dir(os_name):
    return os.path.join(ISO_DIR, ".boot", os_name)

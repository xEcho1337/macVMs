import os
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from hashlib import sha256
from pathlib import Path

from .config import DEBIAN_PRESEED_TEMPLATE, ISOS, boot_cache_dir, qemu_config_path, seed_dir
from .ui import console

QEMU_CONFIG_TEMPLATE = """# Per-VM QEMU overrides for macVMs
# Supported keys:
#   network=user|vmnet-shared|vmnet-bridged
#   ifname=en0
#   nic_model=e1000
#   hostfwd=tcp::2222-:22;tcp::8080-:80
#   extra_args=-device virtio-net-pci,netdev=net0
#   qemu_args=-netdev vmnet-shared,id=net0 -device virtio-net-pci,netdev=net0
#
# Leave this file as-is to keep the default NAT networking.
network=user
"""

SUPPORTED_NETWORK_MODES = {"user", "vmnet-shared", "vmnet-bridged"}
DEFAULT_NET_ID = "net0"
DEFAULT_NIC_MODEL = "e1000"
DEFAULT_HOSTFWD = ["hostfwd=tcp::2222-:22"]
NETWORK_OPTION_KEYS = {
    "network",
    "ifname",
    "hostfwd",
    "nic_model",
    "extra_args",
    "qemu_args",
}


def build_shared_args(shared_path):
    if not shared_path:
        return []

    return [
        "-fsdev", f"local,id=fsdev0,path={shared_path},security_model=none",
        "-device", "virtio-9p-pci,fsdev=fsdev0,mount_tag=shared",
    ]


def qemu_headless_args():
    return [
        "-display", "none",
        "-monitor", "none",
        "-serial", "stdio",
    ]


def ensure_qemu_config(name):
    path = qemu_config_path(name)
    if os.path.exists(path):
        return path

    with open(path, "w", encoding="utf-8") as f:
        f.write(QEMU_CONFIG_TEMPLATE)
    return path


def parse_qemu_config(name):
    path = qemu_config_path(name)
    if not os.path.exists(path):
        return {}

    parsed = {}
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if "=" not in line:
                raise ValueError(f"Invalid qemu.conf entry on line {lineno}: {raw_line.strip()}")

            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key:
                parsed[key] = value

    return parsed


def split_qemu_args(raw_value, label):
    if not raw_value:
        return []

    try:
        return shlex.split(raw_value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} in qemu.conf: {exc}") from exc


def normalize_hostfwd_entries(raw_value):
    if not raw_value:
        return list(DEFAULT_HOSTFWD)

    entries = []
    for chunk in raw_value.split(";"):
        entry = chunk.strip()
        if not entry:
            continue
        if entry.startswith("hostfwd="):
            entries.append(entry)
        else:
            entries.append(f"hostfwd={entry}")
    return entries or list(DEFAULT_HOSTFWD)


def generate_vm_mac(name):
    digest = sha256(name.encode("utf-8")).digest()
    return "52:54:00:{:02x}:{:02x}:{:02x}".format(digest[0], digest[1], digest[2])


def parse_mac_address(device_arg):
    if not device_arg:
        return None

    for chunk in device_arg.split(","):
        if chunk.startswith("mac="):
            return chunk.split("=", 1)[1].lower()
    return None


def append_mac_to_device_arg(device_arg, mac_address):
    if not mac_address or "netdev=" not in device_arg or "mac=" in device_arg:
        return device_arg
    return f"{device_arg},mac={mac_address}"


def ensure_network_identity(config):
    if config.get("mac_address"):
        return False

    config["mac_address"] = generate_vm_mac(config["name"])
    return True


def parse_qemu_overrides(config):
    overrides = parse_qemu_config(config["name"])
    unknown_keys = sorted(set(overrides) - NETWORK_OPTION_KEYS)
    if unknown_keys:
        console.print(
            f"[yellow]Ignoring unsupported qemu.conf keys for {config['name']}: {', '.join(unknown_keys)}[/yellow]"
        )

    extra_args = split_qemu_args(overrides.get("extra_args", ""), "extra_args")
    qemu_args = split_qemu_args(overrides.get("qemu_args", ""), "qemu_args")

    network_mode = overrides.get("network", "user").strip().lower() or "user"
    if network_mode not in SUPPORTED_NETWORK_MODES:
        raise ValueError(
            f"Unsupported network mode '{network_mode}' in qemu.conf. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_NETWORK_MODES))}"
        )

    nic_model = overrides.get("nic_model", DEFAULT_NIC_MODEL).strip() or DEFAULT_NIC_MODEL
    ifname = overrides.get("ifname", "").strip()
    hostfwd = normalize_hostfwd_entries(overrides.get("hostfwd", ""))

    return {
        "network_mode": network_mode,
        "nic_model": nic_model,
        "ifname": ifname,
        "hostfwd": hostfwd,
        "extra_args": extra_args,
        "qemu_args": qemu_args,
    }


def raw_args_define_netdev(tokens):
    return any(token in {"-net", "-netdev", "-nic"} for token in tokens)


def raw_args_define_net_device(tokens):
    if "-nic" in tokens:
        return True
    for index, token in enumerate(tokens):
        if token == "-device" and index + 1 < len(tokens) and "netdev=" in tokens[index + 1]:
            return True
        if token.startswith("-device") and "netdev=" in token:
            return True
    return False


def infer_network_mode_from_tokens(tokens):
    for index, token in enumerate(tokens):
        if token in {"-netdev", "-nic"} and index + 1 < len(tokens):
            option_value = tokens[index + 1]
            mode = option_value.split(",", 1)[0].strip()
            if mode in SUPPORTED_NETWORK_MODES:
                return mode
        elif token.startswith("-nic="):
            mode = token.split("=", 1)[1].split(",", 1)[0].strip()
            if mode in SUPPORTED_NETWORK_MODES:
                return mode
    return None


def inject_mac_into_raw_network_args(tokens, mac_address):
    if not mac_address:
        return list(tokens)

    updated = list(tokens)
    index = 0
    while index < len(updated):
        token = updated[index]
        if token == "-device" and index + 1 < len(updated):
            updated[index + 1] = append_mac_to_device_arg(updated[index + 1], mac_address)
            index += 2
            continue
        if token == "-nic" and index + 1 < len(updated):
            updated[index + 1] = append_mac_to_device_arg(updated[index + 1], mac_address)
            index += 2
            continue
        index += 1
    return updated


def build_managed_network_args(config, overrides):
    netdev_parts = []
    if overrides["network_mode"] == "user":
        netdev_parts = ["user", f"id={DEFAULT_NET_ID}", *overrides["hostfwd"]]
    elif overrides["network_mode"] == "vmnet-shared":
        netdev_parts = ["vmnet-shared", f"id={DEFAULT_NET_ID}"]
    elif overrides["network_mode"] == "vmnet-bridged":
        if not overrides["ifname"]:
            raise ValueError("vmnet-bridged requires ifname=<host interface> in qemu.conf")
        netdev_parts = ["vmnet-bridged", f"id={DEFAULT_NET_ID}", f"ifname={overrides['ifname']}"]

    mac_address = config.get("mac_address")
    device_value = f"{overrides['nic_model']},netdev={DEFAULT_NET_ID}"
    if mac_address:
        device_value += f",mac={mac_address}"

    return {
        "netdev_args": ["-netdev", ",".join(netdev_parts)],
        "device_args": ["-device", device_value],
        "mode": overrides["network_mode"],
        "mac_address": mac_address,
    }


def resolve_network_args(config):
    overrides = parse_qemu_overrides(config)
    raw_tokens = inject_mac_into_raw_network_args(
        [*overrides["qemu_args"], *overrides["extra_args"]],
        config.get("mac_address"),
    )
    managed = build_managed_network_args(config, overrides)

    network_args = []
    if not raw_args_define_netdev(raw_tokens):
        network_args += managed["netdev_args"]
    if not raw_args_define_net_device(raw_tokens):
        network_args += managed["device_args"]

    network_args += raw_tokens

    mac_address = managed["mac_address"]
    if raw_args_define_net_device(raw_tokens):
        for index, token in enumerate(raw_tokens):
            if token == "-device" and index + 1 < len(raw_tokens):
                mac_address = parse_mac_address(raw_tokens[index + 1]) or mac_address
            elif token.startswith("-device"):
                mac_address = parse_mac_address(token) or mac_address

    return {
        "args": network_args,
        "mode": infer_network_mode_from_tokens(raw_tokens) or managed["mode"],
        "mac_address": mac_address,
    }


def find_vm_ip_by_mac(mac_address, lease_file="/var/db/dhcpd_leases"):
    if not mac_address or not os.path.exists(lease_file):
        return None

    with open(lease_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    normalized_mac = mac_address.lower()
    matches = []
    for block in re.findall(r"\{.*?\}", content, flags=re.DOTALL):
        ip_match = re.search(r"ip_address=(.+)", block)
        hw_match = re.search(r"hw_address=(.+)", block)
        lease_match = re.search(r"lease=(.+)", block)
        if not ip_match or not hw_match:
            continue

        hw_address = hw_match.group(1).strip().split(",", 1)[-1].lower()
        if hw_address != normalized_mac:
            continue

        lease_value = lease_match.group(1).strip() if lease_match else "0x0"
        try:
            lease_order = int(lease_value, 16)
        except ValueError:
            lease_order = 0
        matches.append((lease_order, ip_match.group(1).strip()))

    if not matches:
        return None

    matches.sort()
    return matches[-1][1]


def wait_for_vm_ip(mac_address, timeout=120, interval=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ip_address = find_vm_ip_by_mac(mac_address)
        if ip_address:
            return ip_address
        time.sleep(interval)
    return None


def render_debian_preseed(shared_path):
    shared_late_command = ""
    if shared_path:
        shared_late_command = (
            "; mkdir -p /target/mnt/shared"
            "; echo \"shared /mnt/shared 9p trans=virtio,version=9p2000.L,rw 0 0\" >> /target/etc/fstab"
            "; chmod 777 /target/mnt/shared"
        )
    return DEBIAN_PRESEED_TEMPLATE.format(shared_late_command=shared_late_command)


def write_debian_preseed(name, shared_path):
    directory = seed_dir(name)
    os.makedirs(directory, exist_ok=True)
    preseed_path = os.path.join(directory, "preseed.cfg")
    with open(preseed_path, "w", encoding="utf-8") as f:
        f.write(render_debian_preseed(shared_path))
    return directory


def find_iso_member(iso_path, candidates):
    result = subprocess.run(
        ["bsdtar", "-tf", iso_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to inspect ISO contents")

    members = set(line.strip() for line in result.stdout.splitlines())
    for candidate in candidates:
        if candidate in members:
            return candidate
    return None


def extract_iso_member(iso_path, member_path, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as out_file:
        result = subprocess.run(
            ["bsdtar", "-xOf", iso_path, member_path],
            stdout=out_file,
            stderr=subprocess.PIPE,
        )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.decode("utf-8", errors="replace").strip() or f"Failed to extract {member_path}"
        )


def ensure_installer_boot_files(os_name):
    iso_path = ISOS[os_name]["file"]
    boot_info = ISOS[os_name]["boot"]
    cache_dir = boot_cache_dir(os_name)
    kernel_path = os.path.join(cache_dir, "vmlinuz")
    initrd_path = os.path.join(cache_dir, "initrd")

    if os.path.exists(kernel_path) and os.path.exists(initrd_path):
        return kernel_path, initrd_path

    kernel_member = find_iso_member(iso_path, boot_info["kernel_candidates"])
    initrd_member = find_iso_member(iso_path, boot_info["initrd_candidates"])

    if not kernel_member or not initrd_member:
        raise RuntimeError(
            f"Could not find installer boot files inside {Path(iso_path).name}. "
            "The ISO layout may have changed."
        )

    extract_iso_member(iso_path, kernel_member, kernel_path)
    extract_iso_member(iso_path, initrd_member, initrd_path)
    return kernel_path, initrd_path


def build_install_qemu_cmd(name, os_name, ram, cpu, disk, shared_path):
    kernel_path, initrd_path = ensure_installer_boot_files(os_name)

    qemu_cmd = [
        "qemu-system-x86_64",
        "-accel", "tcg",
        "-m", str(ram),
        "-smp", str(cpu),
        "-cpu", "qemu64",
        "-drive", f"file={disk},format=qcow2",
        "-cdrom", ISOS[os_name]["file"],
        "-kernel", kernel_path,
        "-initrd", initrd_path,
        "-append", " ".join(ISOS[os_name]["boot"]["append"]),
    ]

    qemu_cmd += qemu_headless_args()
    qemu_cmd += build_shared_args(shared_path)
    return qemu_cmd


def build_start_qemu_cmd(config, disk):
    qemu_path = shutil.which('qemu-system-x86_64') or '/opt/homebrew/bin/qemu-system-x86_64'
    qemu_cmd = [
        qemu_path,
        "-accel", "tcg",
        "-m", f"{config['ram']}M",
        "-smp", str(config["cpu"]),
        "-cpu", "qemu64",
        "-drive", f"file={disk},format=qcow2",
    ]
    qemu_cmd += resolve_network_args(config)["args"]
    qemu_cmd += qemu_headless_args()
    qemu_cmd += build_shared_args(config.get("shared_folder"))
    return qemu_cmd


def has_persistent_serial_support(config):
    return config.get("serial_bootstrap_version", 0) >= 1


def stream_interactive_process(cmd, stop_text=None):
    master_fd, slave_fd = pty.openpty()
    old_tty = None
    process = None
    detected_stop_text = False
    output_buffer = ""
    display_buffer = ""

    try:
        if sys.stdin.isatty():
            old_tty = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())

        process = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)

    try:
        while True:
            read_fds = [master_fd]
            if sys.stdin.isatty():
                read_fds.append(sys.stdin.fileno())

            ready, _, _ = select.select(read_fds, [], [], 0.1)

            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""

                if chunk:
                    decoded_chunk = chunk.decode("utf-8", errors="ignore")
                    display_buffer += decoded_chunk

                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()

                    if stop_text and not detected_stop_text:
                        output_buffer = (output_buffer + decoded_chunk)[-4096:]
                        if stop_text in output_buffer:
                            detected_stop_text = True
                            console.print("\n[green]Ubuntu installation completed.[/green]")
                            console.print(
                                "[cyan]Closing the temporary install session so you can boot from disk with 'Start VM'.[/cyan]"
                            )
                            process.send_signal(signal.SIGTERM)

                elif process.poll() is not None:
                    break

            if sys.stdin.isatty() and sys.stdin.fileno() in ready and process.poll() is None:
                try:
                    user_input = os.read(sys.stdin.fileno(), 1024)
                except OSError:
                    user_input = b""

                if user_input:
                    try:
                        os.write(master_fd, user_input)
                    except OSError:
                        break

            if process.poll() is not None:
                break

        return process.wait(), detected_stop_text
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                return process.wait(timeout=5), detected_stop_text
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait(), detected_stop_text
        return 130, detected_stop_text
    finally:
        if old_tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        os.close(master_fd)

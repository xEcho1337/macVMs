import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import tty
from pathlib import Path

from .config import DEBIAN_PRESEED_TEMPLATE, ISOS, boot_cache_dir, seed_dir
from .ui import console

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
KERNEL_TIMESTAMP_RE = re.compile(r"^\[\s*\d+\.\d+\]\s*")
UBUNTU_NOISY_PREFIXES = (
    "raid6:",
    "xor:",
)
UBUNTU_NOISY_SUBSTRINGS = (
    "MB/sec",
    "recovery algorithm",
    "software checksum speed",
)


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
    ]

    append_args = list(ISOS[os_name]["boot"]["append"])

    if os_name == "debian":
        seed_path = write_debian_preseed(name, shared_path)
        qemu_cmd += [
            "-drive", f"file=fat:rw:{seed_path},format=raw,if=virtio,media=disk",
        ]
        append_args = [
            "auto=true",
            "priority=critical",
            "preseed/file=/hd-media/preseed.cfg",
            *append_args,
        ]

    qemu_cmd += ["-append", " ".join(append_args)]
    qemu_cmd += qemu_headless_args()
    qemu_cmd += build_shared_args(shared_path)
    return qemu_cmd


def build_start_qemu_cmd(config, disk):
    qemu_cmd = [
        "qemu-system-x86_64",
        "-accel", "tcg",
        "-m", f"{config['ram']}M",
        "-smp", str(config["cpu"]),
        "-cpu", "qemu64",
        "-drive", f"file={disk},format=qcow2",
    ]
    qemu_cmd += qemu_headless_args()
    qemu_cmd += build_shared_args(config.get("shared_folder"))
    return qemu_cmd


def has_persistent_serial_support(config):
    return config.get("serial_bootstrap_version", 0) >= 1


def is_noisy_ubuntu_line(line):
    plain = ANSI_ESCAPE_RE.sub("", line.replace("\r", "")).lstrip()
    if not plain:
        return False

    without_timestamp = KERNEL_TIMESTAMP_RE.sub("", plain).strip()
    if without_timestamp != plain.strip():
        if not without_timestamp:
            return True
        lowered = without_timestamp.lower()
        return (
            lowered.startswith(UBUNTU_NOISY_PREFIXES)
            or any(token.lower() in lowered for token in UBUNTU_NOISY_SUBSTRINGS)
            or True
        )

    lowered = without_timestamp.lower()
    return lowered.startswith(UBUNTU_NOISY_PREFIXES) or any(
        token.lower() in lowered for token in UBUNTU_NOISY_SUBSTRINGS
    )


def filter_ubuntu_installer_output(text):
    visible_lines = []
    for line in text.splitlines(keepends=True):
        if is_noisy_ubuntu_line(line):
            continue
        visible_lines.append(line)
    return "".join(visible_lines)


def stream_interactive_process(cmd, stop_text=None, output_filter=None):
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

                    if output_filter:
                        complete_lines = re.split(r"(?<=\n)|(?<=\r)", display_buffer)
                        if complete_lines and not complete_lines[-1].endswith(("\n", "\r")):
                            display_buffer = complete_lines.pop()
                        else:
                            display_buffer = ""

                        if complete_lines:
                            filtered = output_filter("".join(complete_lines))
                            if filtered:
                                sys.stdout.write(filtered)
                                sys.stdout.flush()
                    else:
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
        if output_filter and display_buffer:
            filtered = output_filter(display_buffer)
            if filtered:
                sys.stdout.write(filtered)
                sys.stdout.flush()
        if old_tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        os.close(master_fd)

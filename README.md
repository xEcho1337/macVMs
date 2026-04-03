# macVMs

macVMs is a small CLI tool to manage QEMU virtual machines.
It is designed to simplify the creation and usage of fully emulated x86 VMs, especially on ARM-based MacBooks.

The interface is interactive and menu-driven, so no manual QEMU commands are required.

## Features

* Automatic ISO download
* VM creation with configurable RAM, CPU and disk
* Start, inspect and delete VMs
* Fully headless install path for serial-only terminals
* Optional shared folder (host ↔ guest via 9p)

The tool focuses on being minimal and predictable rather than feature-rich.

## Installation

Requirements:

* VM/OS installation knowledge
* Python 3.9+
* QEMU (`qemu-system-x86_64`, `qemu-img`)

Clone the repository:

```bash
git clone https://github.com/xEcho1337/macVMs
```

Install QEMU (macOS):

```bash
brew install qemu
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the tool:

```bash
python macvms.py
```

Follow the interactive menu to create and manage VMs.

## Creating a VM

During setup you will choose:

* VM name
* Operating system (Debian, Ubuntu)
* RAM, CPU cores, disk size
* Optional shared folder

The tool will automatically:

1. Download the ISO (if needed)
2. Create a QCOW2 disk
3. Start the installer

The installer now boots directly on the serial console in headless mode.

For Debian, the tool also writes persistent GRUB serial settings during installation so subsequent boots remain visible in the terminal.

Ubuntu is started in serial-friendly installer mode too. When the installer reaches the final "remove installation medium" prompt, `macVMs` closes the temporary install session automatically so you can boot the installed system cleanly with `Start VM`.

## Recommended setup

For a lightweight VM, avoid installing a graphical environment.

At the *software selection* step:

* Keep only **standard system utilities**
* Do not select any desktop environment (GNOME, KDE, etc.)

This results in a minimal system that boots directly into a terminal.

## Shared folders

If configured, a host directory is exposed to the VM using QEMU 9p.

Inside the guest, mount it manually:

```bash
mkdir /mnt/shared
mount -t 9p -o trans=virtio shared /mnt/shared
```

The mount point can be changed as needed.

## Notes

* Uses QEMU in full emulation mode (TCG)
* No hardware virtualization required
* Lower performance is expected compared to native virtualization

## Scope

macVMs is intended for simple and reproducible VM setups, such as Cybersecurity environments, testing and development.

**Note: It is not intended to replace full virtualization platforms.**

## License

macVMs is maintained by xEcho1337 and is licensed under the Apache License, Version 2.0.
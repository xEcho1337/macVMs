#!/bin/bash
set -e

echo "[macVMs] Setting up macvms command..."

if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
    echo "[macVMs] Generating SSH key..."
    ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -N ""
else
    echo "[macVMs] SSH key already exists, skipping..."
fi

echo "[macVMs] Copying SSH key to VM..."
ssh-copy-id -p 2222 root@localhost || true

CMD_PATH="/usr/local/bin/macvms"

echo "[macVMs] Creating macvms command at $CMD_PATH..."

sudo tee "$CMD_PATH" > /dev/null << 'EOF'
#!/bin/bash

HOST_DIR="$PWD"
VM_DIR="/mnt/shared${HOST_DIR}"

ssh -t root@localhost -p 2222 "cd '$VM_DIR' 2>/dev/null || cd /mnt/shared; exec \$SHELL -l"
EOF

sudo chmod +x "$CMD_PATH"

echo "[macVMs] Done! Now you can use 'macvms' from anywhere."
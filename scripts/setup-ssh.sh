#!/bin/bash
ssh-keygen -t ed25519
ssh-copy-id -p 2222 root@localhost
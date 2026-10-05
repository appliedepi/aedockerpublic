#!/bin/bash
# rbase entrypoint: optional SSH access, controlled by one setting.
#
# SSH_PUBKEY is the ONLY trigger. Set it to a public key, and sshd starts
# with that key installed. Leave it unset or empty, and sshd does not start.
# There is no separate "enable" flag. Two settings (an enable flag PLUS a
# key) allow a state where SSH is "on" with no key. The script would then
# need a rule for that state. With one setting, that state cannot exist.
#
# No key is in the image. This file installs only the key that the operator
# supplies, at container start. Host keys are generated fresh per container
# at start, and are never in the image. See the build-time sshd check in
# rbase/4.3.2/Dockerfile. That check deletes the keys it generates in the
# same layer.
set -euo pipefail

if [ -n "${SSH_PUBKEY:-}" ]; then
  ssh-keygen -A                       # fresh host keys for THIS container only
  mkdir -p /run/sshd                  # sshd's privilege-separation directory
  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  printf '%s\n' "$SSH_PUBKEY" > /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
  /usr/sbin/sshd
fi

exec "$@"

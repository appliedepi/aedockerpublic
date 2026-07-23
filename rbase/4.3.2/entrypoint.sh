#!/bin/bash
# rbase entrypoint: optional SSH access, gated on a single knob.
#
# SSH_PUBKEY is the ONLY trigger. Set it to a public key -> sshd starts and
# that key is installed. Leave it unset, or set it to an empty string -> no
# sshd, no exceptions. There is no separate "enable" flag: a design with two
# knobs (an enable flag PLUS a key) has a state where SSH is "on" with no
# key configured, which then has to be handled carefully (start anyway with
# no auth path? refuse silently? warn?). Collapsing to one knob makes that
# state impossible to express, rather than handling it after the fact.
#
# No key is ever baked into the image (this file installs whatever the
# operator supplies, at container-start time, nothing else). Host keys are
# generated fresh per container, also at start time, also never baked into
# the image (see rbase/4.3.2/Dockerfile's build-time sshd check, which
# deletes the keys it generates for that check in the same layer).
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

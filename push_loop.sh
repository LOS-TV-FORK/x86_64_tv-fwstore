#!/bin/bash
cd /tmp/opencode/vadec/fwstore
for i in $(seq 1 40); do
  echo "=== attempt $i $(date +%H:%M:%S) ==="
  git push origin main && echo PUSH_OK && exit 0
  sleep 15
done
echo PUSH_FAILED

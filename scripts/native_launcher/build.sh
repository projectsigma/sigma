#!/usr/bin/env bash
# Fail-fast reproducible cross-build, requires clang, lld-link, Python 3 and gcc for tests.
set -euo pipefail
cd "$(dirname "$0")"

python3 build_resources.py
for lib in kernel32 user32 shell32 ws2_32; do
  lld-link /lib /def:"${lib}.def" /machine:x64 /out:"${lib}.lib"
done
clang -target x86_64-pc-windows-msvc -std=c11 -c sigma_native.c -o sigma_native.obj \
  -Oz -ffreestanding -fno-stack-protector -fno-builtin -Wall -Wextra -Werror
clang -target x86_64-pc-windows-msvc -std=c11 -c support.c -o support.obj \
  -Oz -ffreestanding -fno-stack-protector -fno-builtin -Wall -Wextra -Werror
clang -target x86_64-pc-windows-msvc -c chkstk.s -o chkstk.obj
lld-link /Brepro /subsystem:windows /entry:mainCRTStartup /nodefaultlib \
  /out:sigma.exe sigma_native.obj support.obj chkstk.obj sigma.res \
  kernel32.lib user32.lib shell32.lib ws2_32.lib
python3 test_safety.py "$(pwd)/sigma.exe"
echo 'PASS: SIGMA executable built; no release/copy step occurs before tests pass.'

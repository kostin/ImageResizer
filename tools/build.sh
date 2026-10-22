#!/usr/bin/env bash
# Сборка ImageResizer для macOS (или Linux) в один исполняемый файл.
#
#   ./tools/build.sh                 # тесты + сборка
#   SKIP_TESTS=1 ./tools/build.sh    # только сборка
#   PYTHON=python3.12 ./tools/build.sh
#
# Результат: dist/ImageResizer — внутрь упакованы Python и Pillow,
# на целевой машине ничего устанавливать не нужно.

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

python_bin="${PYTHON:-python3}"

echo "== Зависимости =="
if ! "$python_bin" -c "import PIL, PyInstaller" >/dev/null 2>&1; then
  echo "Устанавливаю зависимости из requirements.txt..."
  "$python_bin" -m pip install --upgrade -r requirements.txt
fi

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  echo "== Тесты =="
  "$python_bin" -m unittest discover -s tests -v
fi

echo "== Сборка =="
"$python_bin" -m PyInstaller --noconfirm --clean ImageResizer.spec

binary="dist/ImageResizer"
if [[ ! -f "$binary" ]]; then
  echo "Не найден $binary" >&2
  exit 1
fi
chmod +x "$binary"

echo
echo "Готово: $binary ($(du -h "$binary" | cut -f1))"

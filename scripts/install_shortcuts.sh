#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="${HOME}/.local/bin"

mkdir -p "$install_dir"

ln -sfn "${repo_dir}/bin/reg" "${install_dir}/reg"
ln -sfn "${repo_dir}/bin/oauth" "${install_dir}/oauth"

chmod +x "${repo_dir}/bin/reg" "${repo_dir}/bin/oauth"

case ":${PATH}:" in
  *":${install_dir}:"*) path_ready=1 ;;
  *) path_ready=0 ;;
esac

echo "Installed:"
echo "  ${install_dir}/reg -> ${repo_dir}/bin/reg"
echo "  ${install_dir}/oauth -> ${repo_dir}/bin/oauth"

if [[ "$path_ready" -eq 0 ]]; then
  echo
  echo "Add this to your shell rc file if reg/oauth are not found:"
  echo "  export PATH=\"${install_dir}:\$PATH\""
fi

echo
echo "Examples:"
echo "  reg 1"
echo "  oauth 1"
echo "  oauth 3"

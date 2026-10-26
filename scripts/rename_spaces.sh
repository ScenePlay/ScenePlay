#!/bin/bash
# Rename files whose names contain spaces, replacing each space with "_".
#
#   scripts/rename_spaces.sh DIR              preview only (nothing renamed)
#   scripts/rename_spaces.sh DIR --apply      do the renames
#   scripts/rename_spaces.sh DIR -r --apply   include sub-folders
#
# Files only (folders are left alone). A rename is skipped when the target
# name already exists, so nothing is ever overwritten.
set -u

DIR=""; APPLY=0; DEPTH=(-maxdepth 1)
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        -r|--recursive) DEPTH=() ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) DIR="$arg" ;;
    esac
done
if [ -z "$DIR" ] || [ ! -d "$DIR" ]; then
    echo "usage: $0 DIR [--apply] [-r]   (DIR must be an existing folder)" >&2
    exit 1
fi

count=0; skipped=0
while IFS= read -r -d '' path; do
    name=$(basename "$path")
    parent=$(dirname "$path")
    new="${name// /_}"
    target="$parent/$new"
    if [ -e "$target" ]; then
        echo "SKIP (exists): $path -> $new"
        skipped=$((skipped + 1))
        continue
    fi
    if [ "$APPLY" -eq 1 ]; then
        mv -- "$path" "$target" && echo "renamed: $path -> $new"
    else
        echo "would rename: $path -> $new"
    fi
    count=$((count + 1))
done < <(find "$DIR" "${DEPTH[@]}" -type f -name '* *' -print0)

if [ "$APPLY" -eq 1 ]; then
    echo "$count renamed, $skipped skipped."
else
    echo "$count would be renamed, $skipped skipped. Add --apply to do it."
fi

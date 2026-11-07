#!/bin/sh
# Fetch pinned upstream repos into .upstream/<KEY>. See PLAN.md 1.1.
set -eu

pins() {
    cat "${PINS_FILE:-upstream-pins.txt}"
}

outdated() {
    pins | while read -r key url ref sha; do
        tag=$(git ls-remote --tags --refs --sort=-v:refname "$url" |
            head -n 1 | sed 's|.*refs/tags/||')
        head_sha=$(git ls-remote "$url" HEAD | cut -f1)
        [ -n "$tag" ] || tag=none
        if [ "$ref" = "-" ]; then shown=$(echo "$sha" | cut -c1-7)
        else shown=$ref; fi
        state=BEHIND
        if [ "$ref" = "$tag" ] || [ "$sha" = "$head_sha" ]; then
            state=UP-TO-DATE
        fi
        echo "$key pinned $shown newest-tag $tag head" \
            "$(echo "$head_sha" | cut -c1-7) $state"
    done
}

fetch() {
    mkdir -p .upstream
    pins | while read -r key url ref sha; do
        dir=.upstream/$key
        have=$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)
        if [ "$have" != "$sha" ]; then
            rm -rf "$dir"
            mkdir -p "$dir"
            git -C "$dir" init -q
            git -C "$dir" remote add origin "$url"
            if [ "$ref" = "-" ]; then
                git -C "$dir" fetch -q --depth 1 origin "$sha"
            else
                git -C "$dir" fetch -q --depth 1 origin tag "$ref"
            fi
            git -C "$dir" checkout -q --detach FETCH_HEAD
            got=$(git -C "$dir" rev-parse HEAD)
            if [ "$got" != "$sha" ]; then
                echo "$key tag moved: $ref"
                exit 1
            fi
        fi
        echo "$key $ref $sha"
    done
}

fetch_new() {
    out=$1
    mkdir -p "$out"
    pins | while read -r key url _ref sha; do
        dir=$out/$key
        rm -rf "$dir"
        mkdir -p "$dir"
        git -C "$dir" init -q
        git -C "$dir" remote add origin "$url"
        tag=$(git ls-remote --tags --refs --sort=-v:refname "$url" |
            head -n 1 | sed 's|.*refs/tags/||')
        if [ -n "$tag" ]; then
            git -C "$dir" fetch -q --filter=blob:none origin \
                "refs/tags/$tag:refs/tags/$tag" "$sha"
            git -C "$dir" merge-base --is-ancestor "$sha" "$tag^{commit}" ||
                tag=
        fi
        if [ -n "$tag" ]; then
            git -C "$dir" fetch -q --depth 1 origin tag "$tag"
        else
            git -C "$dir" fetch -q --depth 1 origin HEAD
        fi
        git -C "$dir" checkout -q --detach FETCH_HEAD
        echo "$key ${tag:--} $(git -C "$dir" rev-parse HEAD)"
    done
}

case "${1:-}" in
    --outdated) outdated ;;
    --new-dir)
        [ -n "${2:-}" ] || { echo "usage: $0 --new-dir <dir>" >&2; exit 2; }
        fetch_new "$2"
        ;;
    *) fetch ;;
esac

#!/usr/bin/env bash
# Releases an AXoR version the way v2.0 and v3.0 were released: an annotated tag "vX.Y" on main, a source zip made with
# git archive (prefix axor-X.Y/) and release notes (the commits since the previous release tag), both next to the repository,
# then main and the tag pushed to origin; with --github, also a GitHub Release from the tag with the zip and notes attached
# (needs gh signed in to the repository owner's account: gh auth switch).
#
#   k8s/release.sh 5.0              check, test, tag, zip, notes; nothing leaves this machine
#   k8s/release.sh 5.0 --push       the same, then push main and the tag to origin
#   k8s/release.sh 5.0 --push --github   …and the GitHub Release
#   k8s/release.sh 5.0 --dry-run    only the checks: says what it would do
#   k8s/release.sh 5.1.0 …          X.Y or X.Y.Z (tag v5.1.0, zip axor-5.1.0.zip)
#
# Options:
#   --out DIR        where the zip and notes go (default: the repository's parent directory, e.g. /home/thomas)
#   --skip-tests     don't run tests/run-unit.sh (needs a local axor/web image; it runs by default)
#   --github         after the push, create the GitHub Release (title "AXoR X.Y", the notes as its text, zip + notes attached)
#   --deploy-ok      push even when the auto-update timer is active: then a push to main IS a production deploy
#   --notes FILE     a written summary that goes above the generated commit list in the notes (and the GitHub Release)
#   --allow-dirty    release HEAD although other work is uncommitted in this tree (e.g. another session's): the tag, zip
#                    and tests all use HEAD exactly (the tests run in a temporary git worktree of HEAD); the notes list the
#                    uncommitted paths that are NOT in the release
#
# It refuses to release when: the version isn't X.Y[.Z]; you're not on main; the working tree has uncommitted changes to tracked
# files without --allow-dirty (the tag must be exactly what was tested); the tag already exists; main.py's FastAPI version isn't it
# (that's what /api/health reports); main is behind origin/main; or the unit tests fail.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD

die() { echo "release: $*" >&2; exit 1; }
say() { echo "== $*"; }

ver= push=0 dry=0 tests=1 deploy_ok=0 github=0 dirty_ok=0 written= out=$(dirname "$REPO")
while (($#)); do
  case $1 in
    --push) push=1; shift ;;
    --dry-run) dry=1; shift ;;
    --skip-tests) tests=0; shift ;;
    --deploy-ok) deploy_ok=1; shift ;;
    --github) github=1; shift ;;
    --allow-dirty) dirty_ok=1; shift ;;
    --notes) written=${2:?--notes needs a file}; shift 2 ;;
    --out) out=${2:?--out needs a directory}; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) [[ -z $ver ]] || die "one version only"; ver=$1; shift ;;
  esac
done
[[ -n $ver ]] || die "give the version, e.g. k8s/release.sh 5.0"
[[ $ver =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || die "version must look like 5.0 or 5.1.0, not '$ver'"
[[ -z $written || -f $written ]] || die "no notes file $written"
tag=v$ver name=axor-$ver
zip=$out/$name.zip notes=$out/$name-notes.md

# ---------- checks ----------
branch=$(git rev-parse --abbrev-ref HEAD)
[[ $branch == main ]] || die "on '$branch': releases are made from main"
dirty=
if ! git diff --quiet || ! git diff --cached --quiet; then
  git status --short --untracked-files=no >&2
  ((dirty_ok)) || die "uncommitted changes to tracked files: commit them first, so the tag is exactly what was tested (or --allow-dirty)"
  dirty=$(git status --short --untracked-files=no | awk '{print $2}')
  say "--allow-dirty: $(wc -l <<<"$dirty") uncommitted path(s) stay out of the release; tests run on HEAD in a worktree"
fi
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "tag $tag already exists (at $(git rev-list -n1 "$tag" | cut -c1-7))"
app_ver=$(sed -n 's/^app = FastAPI(.*version="\([^"]*\)".*/\1/p' backend/app/main.py)
[[ $app_ver == "$ver" ]] || die "backend/app/main.py says version \"$app_ver\"; set it to \"$ver\" (it's what /api/health reports) and commit"
[[ -d $out ]] || die "output directory $out doesn't exist"
[[ -e $zip ]] && die "$zip already exists; move it away or pass --out"

say "fetching origin"
git fetch -q origin main --tags || die "can't reach origin"
behind=$(git rev-list --count HEAD..origin/main)
((behind == 0)) || die "main is $behind commit(s) behind origin/main: pull first"
ahead=$(git rev-list --count origin/main..HEAD)
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "tag $tag exists on origin"

((github && !push)) && die "--github needs --push: the Release is made from the pushed tag"
repo=$(git remote get-url origin | sed -E 's#^(git@[^:]+:|https://github.com/)##; s#\.git$##')
if ((github)); then
  command -v gh >/dev/null || die "--github needs the gh CLI"
  gh repo view "$repo" --json name >/dev/null 2>&1 || die "gh can't see $repo: sign in to its owner's account (gh auth switch)"
  gh release view "$tag" -R "$repo" >/dev/null 2>&1 && die "a GitHub Release $tag already exists on $repo"
fi

timer=$(systemctl is-active axor-auto-update.timer 2>/dev/null || true)
if ((push)) && [[ $timer == active ]] && ((!deploy_ok)); then
  die "the auto-update timer is active: pushing main deploys production. Pass --deploy-ok if that's what you want"
fi

prev=$(git tag -l 'v[0-9]*.[0-9]*' --sort=-v:refname | head -n1)
head=$(git rev-parse --short HEAD)
say "AXoR $ver: tag $tag at $head on main ($ahead commit(s) not on origin yet)"
say "previous release: ${prev:-none}; auto-update timer: ${timer:-not installed}"
say "zip: $zip"
say "notes: $notes"
if ((dry)); then say "dry run: stopping before tests, tag, zip and push"; exit 0; fi

# ---------- tests ----------
if ((tests)); then
  say "unit tests"
  if [[ -n $dirty ]]; then
    wt=$(mktemp -d "${TMPDIR:-/tmp}/axor-release-XXXXXX")
    git worktree add -q --detach "$wt" HEAD
    trap 'git worktree remove --force "$wt" 2>/dev/null || true' EXIT
    "$wt/tests/run-unit.sh" || die "unit tests failed on HEAD: nothing was tagged"
  else
    tests/run-unit.sh || die "unit tests failed: nothing was tagged"
  fi
else
  say "unit tests skipped (--skip-tests)"
fi

# ---------- notes, tag, zip ----------
range=${prev:+$prev..}HEAD
{
  echo "# AXoR $ver"
  echo
  echo "Released $(date +%Y-%m-%d) from \`$head\` on main${prev:+ (previous release: $prev)}."
  echo
  if [[ -n $written ]]; then cat "$written"; echo; fi
  echo "## Commits"
  echo
  git log --no-merges --format='- %s (%h)' "$range"
  echo
  echo "## Files"
  echo
  echo '```'
  git diff --shortstat "${prev:-$(git rev-list --max-parents=0 HEAD | tail -n1)}" HEAD
  echo '```'
  if [[ -n $dirty ]]; then
    echo
    echo "## Not in this release"
    echo
    echo "Uncommitted in the working tree when it was cut (work in progress elsewhere):"
    echo
    sed 's/^/- /' <<<"$dirty"
  fi
} > "$notes"

git tag -a "$tag" -m "AXoR $ver" HEAD
say "tagged $tag"
git archive --format=zip --prefix="$name/" -o "$zip" "$tag"
say "zip written: $(du -h "$zip" | cut -f1), sha256 $(sha256sum "$zip" | cut -d' ' -f1)"

# ---------- push ----------
if ((push)); then
  git push origin main
  git push origin "$tag"
  say "pushed main and $tag to origin"
  if ((github)); then
    gh release create "$tag" -R "$repo" --verify-tag --title "AXoR $ver" --notes-file "$notes" "$zip" "$notes"
    say "GitHub Release: https://github.com/$repo/releases/tag/$tag"
  else
    say "next: create the GitHub Release (or run with --github): gh release create $tag -R $repo --verify-tag --title 'AXoR $ver' --notes-file $notes $zip $notes"
  fi
else
  say "not pushed (no --push): git push origin main && git push origin $tag"
fi

#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="speakerops-hci"
base_url="${SPEAKEROPS_REHEARSAL_URL:-http://127.0.0.1:38001}"
runs="${SPEAKEROPS_REHEARSAL_RUNS:-3}"
artifact_root="${SPEAKEROPS_REHEARSAL_ARTIFACTS:-${TMPDIR:-/tmp}/speakerops-hci-rehearsal-$(date -u +%Y%m%dT%H%M%SZ)}"
pwcli="${PWCLI:-/Users/jaybhagat/.codex/skills/playwright/scripts/playwright_cli.sh}"
axe_url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js"

usage() {
  echo "usage: tools/rehearse-judge-journey.sh [--runs N] [--artifacts DIR] [--desktop-only|--mobile-only]" >&2
}

viewports=(desktop mobile)
while (($#)); do
  case "$1" in
    --runs) runs="${2:?missing run count}"; shift 2 ;;
    --artifacts) artifact_root="${2:?missing artifact directory}"; shift 2 ;;
    --desktop-only) viewports=(desktop); shift ;;
    --mobile-only) viewports=(mobile); shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ "$runs" =~ ^[1-9][0-9]*$ ]] || { echo "runs must be a positive integer" >&2; exit 2; }
[[ "$base_url" == "http://127.0.0.1:38001" ]] || { echo "refusing unexpected rehearsal URL: $base_url" >&2; exit 2; }
command -v docker >/dev/null
command -v curl >/dev/null
command -v jq >/dev/null
command -v npx >/dev/null
[[ -x "$pwcli" ]] || { echo "Playwright CLI wrapper not found: $pwcli" >&2; exit 2; }

mkdir -p "$artifact_root"
axe_path="$artifact_root/axe-4.10.3.min.js"
curl --fail --silent --show-error --location "$axe_url" --output "$axe_path"

compose=(docker compose -p "$project")
compose_env=(WEB_BIND=127.0.0.1:38001 MOCK_BIND=127.0.0.1:39001 PRETALX_SITE_URL=http://127.0.0.1:38001)

restore_canonical_seed() {
  env "${compose_env[@]}" "${compose[@]}" exec -T web python -m pretalx speakerops_seed >/dev/null
}

cd "$repo_dir"
env "${compose_env[@]}" "${compose[@]}" ps --status running >/dev/null
curl --fail --silent --show-error "$base_url/speakerops-demo/cfp" >/dev/null
trap restore_canonical_seed EXIT

reports=()
overall=0
for ((run=1; run<=runs; run++)); do
  for viewport_name in "${viewports[@]}"; do
    run_dir="$artifact_root/run-${run}-${viewport_name}"
    mkdir -p "$run_dir"
    reports+=("$run_dir/report.json")

    env "${compose_env[@]}" "${compose[@]}" restart mock-accelevents >/dev/null
    env "${compose_env[@]}" "${compose[@]}" exec -T web python -m pretalx speakerops_seed --open-cfp-for-rehearsal >"$run_dir/seed.txt"
    curl --fail --silent --show-error "$base_url/speakerops-demo/cfp" >/dev/null

    if [[ "$viewport_name" == "mobile" ]]; then
      viewport='{"width":390,"height":844}'
    else
      viewport='{"width":1440,"height":1000}'
    fi
    session="speakerops-rehearsal-${$}-${run}-${viewport_name}"
    base_json="$(jq -Rn --arg value "$base_url" '$value')"
    dir_json="$(jq -Rn --arg value "$run_dir" '$value')"
    axe_json="$(jq -Rn --arg value "$axe_path" '$value')"
    pdf_json="$(jq -Rn --arg value "$repo_dir/tests/fixtures/browser/judge-ready-slides.pdf" '$value')"
    code="$(sed -e "s|__BASE_URL__|$base_json|" -e "s|__ARTIFACT_DIR__|$dir_json|" -e "s|__AXE_PATH__|$axe_json|" -e "s|__PDF_FIXTURE__|$pdf_json|" -e "s|__VIEWPORT__|$viewport|" "$repo_dir/tools/rehearse-judge-journey.js")"

    if (
      cd "$run_dir"
      "$pwcli" --session "$session" open "$base_url/speakerops-demo/cfp" >/dev/null
      trap '"$pwcli" --session '"$session"' close >/dev/null 2>&1 || true' EXIT
      "$pwcli" --session "$session" tracing-start >/dev/null
      "$pwcli" --session "$session" --raw run-code "$code" > report.json
      "$pwcli" --session "$session" tracing-stop >/dev/null
      jq -e '.ok == true' report.json >/dev/null
    ); then
      echo "passed run $run $viewport_name: $run_dir/report.json"
    else
      overall=1
      echo "failed run $run $viewport_name: $run_dir/report.json" >&2
    fi
  done
done

jq -s '{generated_at:(now|todate), ok:all(.ok), reports:map({viewport,started_at,finished_at,ok,stages,failures,console_errors,request_failures,http_errors,accessibility})}' "${reports[@]}" > "$artifact_root/summary.json"
echo "rehearsal evidence: $artifact_root/summary.json"
exit "$overall"

{% autoescape off %}#!/bin/sh
# ft: your FinTrack tasks, timer and notes from the terminal.
#   Needs curl. Your token stays in ~/.config/ft/token (or $FT_TOKEN) and is only sent to the site below.
FT_URL="${FT_URL:-{{ base }}}"
TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/ft/token"

usage() {
  cat <<'HELP'
ft login                     save your token (Productivity → Settings → API)
ft add "fix(auth): loop p1"  add a task, written as in quick add
ft ls [status] [words]       open tasks; status: todo doing review done all
ft show T-42                 one task, and where you left off
ft start T-42                start the timer (ft start "reading logs" for no task)
ft stop ["next: …"]          stop it, with where you left off
ft status                    what's running, and today's total
ft doing|review|done T-42    move a task
ft comment T-42 "text"       add a comment
ft branch T-42               print its branch name: git switch -c $(ft branch T-42)
ft commit T-42               print its commit message
ft log "text"                add a line to today's note
ft snip [words]              find a snippet (one match prints just the code)
ft standup                   yesterday, today and blockers, ready to paste
ft hook                      in a repository: add the task key from the branch to each commit
HELP
}

token() {
  if [ -n "$FT_TOKEN" ]; then printf '%s' "$FT_TOKEN"
  elif [ -r "$TOKEN_FILE" ]; then cat "$TOKEN_FILE"
  else echo "No token yet: run ft login" >&2; exit 1; fi
}
quote() { printf '%s' "$1" | tr '\n\t' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
call() {      # METHOD PATH [JSON]
  out=$(curl -sS -X "$1" "$FT_URL/work/api/v1$2" -H "Authorization: Bearer $(token)" -H "Accept: text/plain" \
             -H "Content-Type: application/json" ${3:+-d "$3"} -w '%{http_code}') || exit 1
  code=$(printf '%s' "$out" | tail -n 1)
  printf '%s\n' "$out" | sed '$d'
  [ "$code" -lt 400 ]
}
encode() { printf '%s' "$1" | sed 's/%/%25/g; s/ /%20/g; s/&/%26/g; s/+/%2B/g; s/#/%23/g; s/?/%3F/g'; }

cmd="${1:-help}"; [ $# -gt 0 ] && shift
case "$cmd" in
  login)
    printf 'Token: '; stty -echo 2>/dev/null; read -r t; stty echo 2>/dev/null; echo
    mkdir -p "$(dirname "$TOKEN_FILE")"; (umask 077; printf '%s' "$t" > "$TOKEN_FILE")
    call GET /me/ ;;
  add) call POST /tasks/ "{\"text\": \"$(quote "$*")\"}" ;;
  ls)
    status=open
    case "$1" in todo|doing|review|done|backlog|all|open) status=$1; shift ;; esac
    call GET "/tasks/?status=$status&q=$(encode "$*")" ;;
  show) call GET "/tasks/$1/" ;;
  start)
    case "$1" in
      ""|*[!A-Za-z0-9-]*|*[!0-9]) call POST /timer/ "{\"description\": \"$(quote "$*")\"}" ;;
      *) call POST /timer/ "{\"task\": \"$1\"}" ;;
    esac ;;
  stop) call POST /timer/ "{\"stop\": true, \"left_off\": \"$(quote "$*")\"}" ;;
  status) call GET /me/ ;;
  doing|review|done) call POST "/tasks/$1/" "{\"status\": \"$cmd\"}" ;;
  comment) t=$1; shift; call POST "/tasks/$t/" "{\"comment\": \"$(quote "$*")\"}" ;;
  branch|commit) call GET "/tasks/$1/?field=$cmd" ;;
  log) call POST /log/ "{\"text\": \"$(quote "$*")\"}" ;;
  snip) call GET "/snippets/?q=$(encode "$*")" ;;
  standup) call GET /standup/ ;;
  hook)
    dir=$(git rev-parse --git-path hooks) || exit 1
    mkdir -p "$dir"
    cat > "$dir/commit-msg" <<'HOOK'
#!/bin/sh
# Added by ft: names the task of this branch (fix/T-42-login) in the commit, so it shows up on the task.
key=$(git rev-parse --abbrev-ref HEAD | grep -oE '[A-Za-z]+-[0-9]+' | head -n 1)
[ -n "$key" ] && ! grep -q "$key" "$1" && printf '\n%s\n' "$key" >> "$1"
exit 0
HOOK
    chmod +x "$dir/commit-msg"; echo "Commits on a branch like fix/T-42-login now name T-42." ;;
  help|-h|--help) usage ;;
  *) echo "ft: no such command: $cmd" >&2; usage >&2; exit 1 ;;
esac
{% endautoescape %}

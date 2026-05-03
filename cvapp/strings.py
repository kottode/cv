HELP_TEXT = """\
cv - resume workflow CLI

Usage:
    cv init <name>
    cv install [target]
    cv current
    cv jobs [job] [name]
    cv title <new title>
    cv section [list|show|set|add|edit] ...
    cv skills [list|add|rm|manage] ...
    cv exp [list|add|rm|manage] ...
    cv tags [text|url]
    cv say <question>
    cv fit <text|url>
    cv tailor [text|url]
    cv track [item] [status]
    cv posts [list|all|filtered|show <index>]
    cv auto [status|enable|disable]
    cv ats [senior]
    cv ci telegram [setup|status|send] [message]
    cv help

Examples:
    cv init john-bang-gang
    cv jobs frontend
    cv title Frontend Developer
    cv skills add \"React\"
    cv exp add \"Acme|Frontend Engineer|2022-01|Present\"
    cv fit \"Senior Frontend role with React TypeScript\"
    cv fit https://example.com/jobs/frontend-engineer
    cv tailor https://example.com/jobs/frontend-engineer
    cv tailor \"Senior frontend role with React TypeScript\"
    cv tags
    cv tags https://example.com/jobs/frontend-engineer
    cv posts
    cv auto status
    cv auto enable
    cv ats senior
    cv ci telegram
    cv ci telegram send \"Build finished\"
"""

USAGE_CI = "Usage: cv ci telegram [setup|status|send] [message]"
USAGE_AUTO = "Usage: cv auto [status|enable|disable]"
USAGE_POSTS = "Usage: cv posts [list|all|filtered|show <index>]"
USAGE_TRACK = "Usage: cv track <item> [status]"
UNKNOWN_COMMAND_TEMPLATE = "Unknown command: {cmd}. Run: cv help"

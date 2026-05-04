HELP_TEXT = """\
cv - resume workflow CLI

Usage:
    cv init <name>
    cv current
    cv jobs [job] [name]
    cv title <new title>
    cv section [list|show|set|add|edit] ...
    cv skills [list|add|rm|manage] ...
    cv exp [list|add|rm|manage] ...
    cv tags [text|url]
    cv say <question>
    cv fit <text|url>
    cv gen [current|all|<path>]
    cv tailor [text|url]
    cv track [item] [status]
    cv posts [fetch|fit|list|all|filtered|show <index>]
    cv filters [name|list]
    cv auto [status|enable|disable|schedule|unschedule]
    cv accounts [name]
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
    cv posts fetch
    cv posts fit
    cv posts
    cv filters
    cv filters frontend
    cv auto status
    cv auto enable
    cv accounts linkedin
    cv ats senior
    cv ci telegram
    cv ci telegram send \"Build finished\"
"""

USAGE_CI = "Usage: cv ci telegram [setup|status|send] [message]"
USAGE_AUTO = "Usage: cv auto [status|enable|disable|schedule|unschedule]"
USAGE_POSTS = "Usage: cv posts [fetch|fit|list|all|filtered|show <index>]"
USAGE_FILTERS = "Usage: cv filters [name|list]"
USAGE_GEN = "Usage: cv gen [current|all|<path>]"
USAGE_ACCOUNTS = "Usage: cv accounts [name]"
USAGE_TRACK = "Usage: cv track <item> [status]"
UNKNOWN_COMMAND_TEMPLATE = "Unknown command: {cmd}. Run: cv help"

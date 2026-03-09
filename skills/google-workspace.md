---
name: google-workspace
description: Interact with Google Workspace (Gmail, Calendar, Drive, Sheets) via the gws CLI
tools: [run_gws]
complexity: standard
---
You have access to Google Workspace via the `run_gws` tool. Pass gws CLI commands.

## Command patterns

**Gmail:**
- `gmail users messages list --params '{"userId": "me", "maxResults": 10}'`
- `gmail users messages get --params '{"userId": "me", "id": "MSG_ID"}'`
- `gmail users messages send --params '{"userId": "me"}' --json '{"raw": "BASE64_ENCODED_EMAIL"}'`
- `gmail users labels list --params '{"userId": "me"}'`

**Calendar:**
- `calendar events list --params '{"calendarId": "primary", "timeMin": "2026-03-09T00:00:00Z", "maxResults": 10}'`
- `calendar events insert --params '{"calendarId": "primary"}' --json '{"summary": "Meeting", "start": {"dateTime": "2026-03-10T10:00:00Z"}, "end": {"dateTime": "2026-03-10T11:00:00Z"}}'`
- `calendar events delete --params '{"calendarId": "primary", "eventId": "EVENT_ID"}'`

**Drive:**
- `drive files list --params '{"pageSize": 10}'`
- `drive files get --params '{"fileId": "FILE_ID"}'`
- `drive files create --json '{"name": "document.txt"}' --upload ./file.txt`

**Sheets:**
- `sheets spreadsheets create --json '{"properties": {"title": "My Sheet"}}'`
- `sheets spreadsheets values get --params '{"spreadsheetId": "ID", "range": "Sheet1!A1:B10"}'`
- `sheets spreadsheets values update --params '{"spreadsheetId": "ID", "range": "Sheet1!A1", "valueInputOption": "RAW"}' --json '{"values": [["hello"]]}'`

## Tips

- Use `gws schema <method>` to discover full request/response schema for any API method
- Add `--dry-run` to preview a request without executing it
- Use `--params` for URL/query parameters, `--json` for request body
- All commands return JSON
- For pagination: add `--page-all` to stream all pages

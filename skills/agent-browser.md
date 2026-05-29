---
name: agent-browser
description: Browse and interact with web pages using a headless browser (navigate, click, type, extract content, take screenshots)
tools: [run_browser]
complexity: standard
---
You have access to a headless browser via the `run_browser` tool. Pass agent-browser CLI commands.

## Command patterns

**Navigation:**
- `navigate --url 'https://example.com'`
- `go-back`
- `go-forward`
- `refresh`

**Interaction:**
- `click --selector '#submit-button'`
- `type --selector '#search-input' --text 'search query'`
- `scroll --direction down --amount 500`
- `select --selector '#dropdown' --value 'option1'`
- `hover --selector '.menu-item'`

**Content extraction:**
- `get-text --selector '.main-content'`
- `get-html --selector '#article'`
- `get-attribute --selector 'a.link' --attribute href`
- `evaluate --expression 'document.title'`

**Screenshots:**
- `screenshot --path /tmp/page.png`
- `screenshot --selector '#chart' --path /tmp/chart.png`

**Waiting:**
- `wait --selector '.loaded-content' --timeout 10000`
- `wait --text 'Success'`

## Tips

- Always `navigate` to a URL before trying to interact with the page
- Use CSS selectors for targeting elements
- For dynamic pages, use `wait` before extracting content
- Screenshots are useful for visual verification
- Commands return JSON with the result or page state
- Use `evaluate` for arbitrary JavaScript execution when built-in commands are insufficient

import { render } from 'preact'
import { html } from '../lib/htm.js'
import { App } from '../components/App.js'

render(html`<${App} />`, document.getElementById('app'))

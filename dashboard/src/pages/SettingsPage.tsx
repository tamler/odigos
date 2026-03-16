import { useState } from 'react'
import GeneralSettings from './settings/GeneralSettings'
import EvolutionTab from './settings/EvolutionTab'
import AgentsTab from './settings/AgentsTab'
import PluginsTab from './settings/PluginsTab'
import SkillsTab from './settings/SkillsTab'
import PromptsTab from './settings/PromptsTab'

interface Props {
  needsSetup?: boolean
}

const TABS = [
  { id: 'general', label: 'General' },
  { id: 'skills', label: 'Skills' },
  { id: 'prompts', label: 'Prompts' },
  { id: 'evolution', label: 'Evolution' },
  { id: 'agents', label: 'Agents' },
  { id: 'plugins', label: 'Plugins' },
] as const

type TabId = typeof TABS[number]['id']

export default function SettingsPage({ needsSetup }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>('general')

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="border-b border-border/40 px-4 sm:px-6">
        <div className="max-w-3xl mx-auto flex gap-1 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-3 text-sm font-medium transition-colors relative shrink-0 ${
                activeTab === tab.id
                  ? 'text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-foreground rounded-full" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content — all tabs stay mounted to avoid re-fetching on switch */}
      <div className="flex-1 overflow-y-auto">
        <div className={activeTab === 'general' ? '' : 'hidden'}><GeneralSettings needsSetup={needsSetup} /></div>
        <div className={activeTab === 'skills' ? '' : 'hidden'}><SkillsTab /></div>
        <div className={activeTab === 'prompts' ? '' : 'hidden'}><PromptsTab /></div>
        <div className={activeTab === 'evolution' ? '' : 'hidden'}><EvolutionTab /></div>
        <div className={activeTab === 'agents' ? '' : 'hidden'}><AgentsTab /></div>
        <div className={activeTab === 'plugins' ? '' : 'hidden'}><PluginsTab /></div>
      </div>
    </div>
  )
}

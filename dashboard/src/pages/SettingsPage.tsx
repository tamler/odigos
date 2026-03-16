import { useState } from 'react'
import GeneralSettings from './settings/GeneralSettings'
import AccountTab from './settings/AccountTab'
import EvolutionTab from './settings/EvolutionTab'
import AgentsTab from './settings/AgentsTab'
import PluginsTab from './settings/PluginsTab'
import SkillsTab from './settings/SkillsTab'
import PromptsTab from './settings/PromptsTab'
import ConnectionsTab from './ConnectionsPage'
import FeedTab from './FeedPage'
import InspectorTab from './StatePage'

const TABS = [
  { id: 'account', label: 'Account' },
  { id: 'general', label: 'General' },
  { id: 'skills', label: 'Skills' },
  { id: 'prompts', label: 'Prompts' },
  { id: 'evolution', label: 'Evolution' },
  { id: 'agents', label: 'Agents' },
  { id: 'plugins', label: 'Plugins' },
  { id: 'connections', label: 'Connections' },
  { id: 'feed', label: 'Feed' },
  { id: 'inspector', label: 'Inspector' },
] as const

type TabId = typeof TABS[number]['id']

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('general')

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="border-b border-border/40 px-4 sm:px-6">
        <div className="max-w-4xl mx-auto flex gap-0.5 overflow-x-auto scrollbar-hide" style={{ scrollbarWidth: 'none' }}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-3 text-xs sm:text-sm font-medium transition-colors relative shrink-0 ${
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

      {/* Tab content — all tabs stay mounted; active prop triggers background refetch */}
      <div className="flex-1 overflow-y-auto">
        <div className={activeTab === 'account' ? '' : 'hidden'}><AccountTab active={activeTab === 'account'} /></div>
        <div className={activeTab === 'general' ? '' : 'hidden'}><GeneralSettings active={activeTab === 'general'} /></div>
        <div className={activeTab === 'skills' ? '' : 'hidden'}><SkillsTab active={activeTab === 'skills'} /></div>
        <div className={activeTab === 'prompts' ? '' : 'hidden'}><PromptsTab active={activeTab === 'prompts'} /></div>
        <div className={activeTab === 'evolution' ? '' : 'hidden'}><EvolutionTab active={activeTab === 'evolution'} /></div>
        <div className={activeTab === 'agents' ? '' : 'hidden'}><AgentsTab active={activeTab === 'agents'} /></div>
        <div className={activeTab === 'plugins' ? '' : 'hidden'}><PluginsTab active={activeTab === 'plugins'} /></div>
        <div className={activeTab === 'connections' ? '' : 'hidden'}><ConnectionsTab active={activeTab === 'connections'} /></div>
        <div className={activeTab === 'feed' ? '' : 'hidden'}><FeedTab active={activeTab === 'feed'} /></div>
        <div className={activeTab === 'inspector' ? '' : 'hidden'}><InspectorTab active={activeTab === 'inspector'} /></div>
      </div>
    </div>
  )
}

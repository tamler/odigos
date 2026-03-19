import { useState } from 'react'
import GeneralSettings from './settings/GeneralSettings'
import AccountTab from './settings/AccountTab'
import EvolutionTab from './settings/EvolutionTab'
import AgentsTab from './settings/AgentsTab'
import PluginsTab from './settings/PluginsTab'
import SkillsTab from './settings/SkillsTab'
import PromptsTab from './settings/PromptsTab'
import DocumentsTab from './settings/DocumentsTab'
import ConnectionsTab from './ConnectionsPage'
import FeedTab from './FeedPage'
import InspectorTab from './StatePage'
import PeerConfigTab from './settings/PeerConfigTab'

const TABS = [
  { id: 'account', label: 'Account' },
  { id: 'general', label: 'General' },
  { id: 'skills', label: 'Skills' },
  { id: 'prompts', label: 'Prompts' },
  { id: 'evolution', label: 'Evolution' },
  { id: 'agents', label: 'Agents' },
  { id: 'plugins', label: 'Plugins' },
  { id: 'documents', label: 'Documents' },
  { id: 'connections', label: 'Connections' },
  { id: 'peers', label: 'Peers' },
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

      {/* Tab content — conditionally remounted per G25 */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'account' && <AccountTab active={true} />}
        {activeTab === 'general' && <GeneralSettings active={true} />}
        {activeTab === 'skills' && <SkillsTab active={true} />}
        {activeTab === 'prompts' && <PromptsTab active={true} />}
        {activeTab === 'evolution' && <EvolutionTab active={true} />}
        {activeTab === 'agents' && <AgentsTab active={true} />}
        {activeTab === 'plugins' && <PluginsTab active={true} />}
        {activeTab === 'documents' && <DocumentsTab active={true} />}
        {activeTab === 'connections' && <ConnectionsTab active={true} />}
        {activeTab === 'peers' && <PeerConfigTab />}
        {activeTab === 'feed' && <FeedTab active={true} />}
        {activeTab === 'inspector' && <InspectorTab active={true} />}
      </div>
    </div>
  )
}

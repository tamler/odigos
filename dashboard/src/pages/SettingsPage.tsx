import { useEffect } from 'react'
import { useParams, useNavigate, useOutletContext } from 'react-router-dom'
import GeneralSettings from './settings/GeneralSettings'
import AccountTab from './settings/AccountTab'
import EvolutionTab from './settings/EvolutionTab'
import AgentsTab from './settings/AgentsTab'
import PluginsTab from './settings/PluginsTab'
import SkillsTab from './settings/SkillsTab'
import PromptsTab from './settings/PromptsTab'
import DocumentsTab from './settings/DocumentsTab'
import AnalyticsTab from './settings/AnalyticsTab'
import MeshTab from './settings/MeshTab'
import IntegrationsTab from './settings/IntegrationsTab'
import AssistantTab from './settings/AssistantTab'
import VoiceTab from './settings/VoiceTab'
import DataTab from './settings/DataTab'
import ConnectionsTab from './ConnectionsPage'
import FeedTab from './FeedPage'
import InspectorTab from './StatePage'
import PeerConfigTab from './settings/PeerConfigTab'
import { 
  ArrowLeft, 
  Settings, 
  User, 
  Volume2, 
  Zap, 
  Terminal, 
  TrendingUp, 
  Puzzle, 
  FileText, 
  Network, 
  Database, 
  BarChart3, 
  Link as LinkIcon, 
  Rss, 
  Eye,
  ChevronRight,
  MessageCircle
} from 'lucide-react'
import { Button } from '@/components/ui/button'

const SECTIONS = [
  { id: 'general', label: 'General', icon: Settings },
  { id: 'account', label: 'Account', icon: User },
  { id: 'voice', label: 'Voice', icon: Volume2 },
  { id: 'skills', label: 'Skills', icon: Zap },
  { id: 'prompts', label: 'Prompts', icon: Terminal },
  { id: 'evolution', label: 'Evolution', icon: TrendingUp },
  { id: 'agents', label: 'Agents', icon: User },
  { id: 'plugins', label: 'Plugins', icon: Puzzle },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'integrations', label: 'Integrations', icon: Zap },
  { id: 'assistant', label: 'Assistant', icon: MessageCircle },
  { id: 'mesh', label: 'Mesh', icon: Network },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'connections', label: 'Connections', icon: LinkIcon },
  { id: 'peers', label: 'Peers', icon: Network },
  { id: 'feed', label: 'Feed', icon: Rss },
  { id: 'inspector', label: 'Inspector', icon: Eye },
] as const

export default function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>()
  const { isMobile, setPageContextData } = useOutletContext<any>()
  const navigate = useNavigate()
  const activeTab = tab || (isMobile ? null : 'general')

  useEffect(() => {
    if (activeTab) {
      setPageContextData({
        page_id: activeTab,
        page_title: `Settings > ${SECTIONS.find(s => s.id === activeTab)?.label || activeTab}`,
      })
    }
    return () => setPageContextData({})
  }, [activeTab, setPageContextData])

  if (isMobile && !activeTab) {
    return (
      <div className="flex-1 flex flex-col bg-background overflow-y-auto">
        <div className="px-4 py-6">
          <h1 className="text-2xl font-bold mb-6 px-2">Settings</h1>
          <div className="space-y-1">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                onClick={() => navigate(`/settings/${s.id}`)}
                className="w-full flex items-center justify-between p-4 rounded-xl border border-border/40 bg-card/50 active:bg-muted transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                    <s.icon className="h-5 w-5 text-primary" />
                  </div>
                  <span className="font-semibold text-sm">{s.label}</span>
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  const resolvedTab = activeTab || 'general'

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-background">
      {/* Header for mobile drill-down */}
      <div className="flex items-center gap-4 px-4 h-[52px] border-b border-border/40 shrink-0 lg:hidden">
        <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => navigate('/settings')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-bold uppercase tracking-widest">
          {SECTIONS.find(s => s.id === resolvedTab)?.label || 'Settings'}
        </h1>
      </div>

      <div className="flex-1 overflow-y-auto">
        {resolvedTab === 'account' && <AccountTab active={true} />}
        {resolvedTab === 'general' && <GeneralSettings active={true} />}
        {resolvedTab === 'skills' && <SkillsTab active={true} />}
        {resolvedTab === 'prompts' && <PromptsTab active={true} />}
        {resolvedTab === 'evolution' && <EvolutionTab active={true} />}
        {resolvedTab === 'agents' && <AgentsTab active={true} />}
        {resolvedTab === 'plugins' && <PluginsTab active={true} />}
        {resolvedTab === 'documents' && <DocumentsTab active={true} />}
        {resolvedTab === 'integrations' && <IntegrationsTab active={true} />}
        {resolvedTab === 'assistant' && <AssistantTab active={true} />}
        {resolvedTab === 'voice' && <VoiceTab active={true} />}
        {resolvedTab === 'data' && <DataTab active={true} />}
        {resolvedTab === 'analytics' && <AnalyticsTab />}
        {resolvedTab === 'mesh' && <MeshTab />}
        {resolvedTab === 'connections' && <ConnectionsTab active={true} />}
        {resolvedTab === 'peers' && <PeerConfigTab />}
        {resolvedTab === 'feed' && <FeedTab active={true} />}
        {resolvedTab === 'inspector' && <InspectorTab active={true} />}
      </div>
    </div>
  )
}

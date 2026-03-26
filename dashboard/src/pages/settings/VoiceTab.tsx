import { useState, useEffect, useCallback } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { Mic, Volume2, Play } from 'lucide-react'

interface VoiceSettings {
  stt_provider: 'groq' | 'local' | 'disabled'
  tts_provider: 'edge' | 'local' | 'disabled'
  tts_voice: string
  groq_model: string
}

const EDGE_VOICES = [
  // US voices
  { id: 'en-US-AvaMultilingualNeural', name: 'Ava (US Female, Natural)' },
  { id: 'en-US-AndrewMultilingualNeural', name: 'Andrew (US Male, Natural)' },
  { id: 'en-US-EmmaMultilingualNeural', name: 'Emma (US Female, Warm)' },
  { id: 'en-US-BrianMultilingualNeural', name: 'Brian (US Male, Clear)' },
  { id: 'en-US-AriaNeural', name: 'Aria (US Female)' },
  { id: 'en-US-JennyNeural', name: 'Jenny (US Female)' },
  { id: 'en-US-GuyNeural', name: 'Guy (US Male)' },
  { id: 'en-US-ChristopherNeural', name: 'Christopher (US Male)' },
  { id: 'en-US-EricNeural', name: 'Eric (US Male)' },
  { id: 'en-US-MichelleNeural', name: 'Michelle (US Female)' },
  { id: 'en-US-RogerNeural', name: 'Roger (US Male)' },
  { id: 'en-US-SteffanNeural', name: 'Steffan (US Male)' },
  // UK voices
  { id: 'en-GB-SoniaNeural', name: 'Sonia (UK Female)' },
  { id: 'en-GB-RyanNeural', name: 'Ryan (UK Male)' },
  { id: 'en-GB-LibbyNeural', name: 'Libby (UK Female)' },
  { id: 'en-GB-ThomasNeural', name: 'Thomas (UK Male)' },
  // Australian
  { id: 'en-AU-NatashaNeural', name: 'Natasha (AU Female)' },
  { id: 'en-AU-WilliamMultilingualNeural', name: 'William (AU Male)' },
  // Other accents
  { id: 'en-IN-NeerjaExpressiveNeural', name: 'Neerja (India Female, Expressive)' },
  { id: 'en-IN-PrabhatNeural', name: 'Prabhat (India Male)' },
  { id: 'en-IE-EmilyNeural', name: 'Emily (Ireland Female)' },
  { id: 'en-IE-ConnorNeural', name: 'Connor (Ireland Male)' },
  { id: 'en-CA-ClaraNeural', name: 'Clara (Canada Female)' },
  { id: 'en-CA-LiamNeural', name: 'Liam (Canada Male)' },
  { id: 'en-PH-RosaNeural', name: 'Rosa (Philippines Female)' },
  { id: 'en-PH-JamesNeural', name: 'James (Philippines Male)' },
  { id: 'en-NZ-MollyNeural', name: 'Molly (NZ Female)' },
  { id: 'en-SG-LunaNeural', name: 'Luna (Singapore Female)' },
  { id: 'en-ZA-LeahNeural', name: 'Leah (South Africa Female)' },
]

export default function VoiceTab({ active: isActive }: { active?: boolean }) {
  const [settings, setSettings] = useState<VoiceSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await get<{ voice: VoiceSettings }>('/api/settings')
      setSettings(data.voice)
    } catch {
      toast.error('Failed to load voice settings')
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (isActive) load() }, [isActive, load])

  async function handleSave() {
    if (!settings) return
    setSaving(true)
    try {
      await post('/api/settings', { voice: settings })
      toast.success('Voice settings saved')
      load()
    } catch {
      toast.error('Failed to save voice settings')
    } finally {
      setSaving(false)
    }
  }

  async function testVoice() {
    if (!settings || testing) return
    setTesting(true)
    try {
      const res = await fetch(`/api/audio/speak?text=${encodeURIComponent('Hello, I am your AI assistant.')}&voice=${settings.tts_voice}`)
      if (!res.ok) throw new Error('Test failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        setTesting(false)
      }
      audio.play()
    } catch {
      toast.error('Voice test failed')
      setTesting(false)
    }
  }

  if (!settings) return null

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 sm:py-6 space-y-8">
      {/* Speech-to-Text (STT) */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Mic className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Speech-to-Text (Transcription)</h2>
        </div>

        <div className="rounded-lg border border-border/40 bg-card p-4 space-y-4 shadow-sm">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select 
                value={settings.stt_provider} 
                onValueChange={(val: any) => setSettings({ ...settings, stt_provider: val })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select STT provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="groq">Groq (Cloud)</SelectItem>
                  <SelectItem value="local">Local (Whisper)</SelectItem>
                  <SelectItem value="disabled">Disabled</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {settings.stt_provider === 'groq' && (
              <div className="space-y-2">
                <Label htmlFor="groq-model">Groq Model</Label>
                <Input
                  id="groq-model"
                  value={settings.groq_model}
                  onChange={(e) => setSettings({ ...settings, groq_model: e.target.value })}
                  placeholder="whisper-large-v3-turbo"
                />
              </div>
            )}
          </div>

          {settings.stt_provider === 'groq' && (
            <p className="text-[11px] text-muted-foreground bg-muted/50 p-2 rounded border border-border/20">
              Note: Groq Whisper is highly accurate and low latency. Cost is approximately $0.04 per hour of audio.
            </p>
          )}
        </div>
      </section>

      {/* Text-to-Speech (TTS) */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Volume2 className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Text-to-Speech (Voice)</h2>
        </div>

        <div className="rounded-lg border border-border/40 bg-card p-4 space-y-4 shadow-sm">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select 
                value={settings.tts_provider} 
                onValueChange={(val: any) => setSettings({ ...settings, tts_provider: val })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select TTS provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="edge">Edge (Free / Cloud)</SelectItem>
                  <SelectItem value="local">Local (Piper)</SelectItem>
                  <SelectItem value="disabled">Disabled</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {settings.tts_provider === 'edge' && (
              <div className="space-y-2">
                <Label>Voice</Label>
                <div className="flex gap-2">
                  <Select 
                    value={settings.tts_voice} 
                    onValueChange={(val) => setSettings({ ...settings, tts_voice: val as string })}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Select voice" />
                    </SelectTrigger>
                    <SelectContent>
                      {EDGE_VOICES.map(v => (
                        <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button 
                    variant="outline" 
                    size="icon" 
                    className="shrink-0 h-8 w-8" 
                    onClick={testVoice}
                    disabled={testing}
                    title="Test voice"
                  >
                    {testing ? <div className="h-3 w-3 border-2 border-primary border-t-transparent rounded-full animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      <div className="flex justify-end pt-4 pb-12">
        <Button onClick={handleSave} disabled={saving} className="w-full sm:w-auto">
          {saving ? 'Saving...' : 'Save Voice Settings'}
        </Button>
      </div>
    </div>
  )
}

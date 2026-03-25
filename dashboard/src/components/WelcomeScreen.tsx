import { useState, useEffect } from 'react'
import { get, post } from '@/lib/api'
import { toast } from 'sonner'
import { Loader } from '@/components/ui/loader'
import { 
  User, 
  BookOpen, 
  MessageSquare, 
  Search, 
  PenTool, 
  TrendingUp,
  Check
} from 'lucide-react'

interface Profile {
  id: string
  name: string
  description: string
}

const PROFILE_ICONS: Record<string, any> = {
  personal: User,
  learner: BookOpen,
  mentor: MessageSquare,
  researcher: Search,
  writer: PenTool,
  sales: TrendingUp,
}

export default function WelcomeScreen({ onComplete }: { onComplete: () => void }) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [loading, setLoading] = useState(true)
  const [selecting, setSelecting] = useState<string | null>(null)

  useEffect(() => {
    get<{ profiles: Profile[] }>('/api/profiles')
      .then(res => setProfiles(res.profiles))
      .catch(() => toast.error('Failed to load profiles'))
      .finally(() => setLoading(false))
  }, [])

  async function selectProfile(id: string) {
    setSelecting(id)
    try {
      await post(`/api/profiles/${id}`)
      localStorage.setItem('profile-selected', 'true')
      toast.success('Profile applied')
      onComplete()
    } catch {
      toast.error('Failed to apply profile')
      setSelecting(null)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 bg-background flex flex-col items-center justify-center z-[100]">
        <Loader size="lg" />
        <p className="mt-4 text-muted-foreground animate-pulse">Initializing Odigos...</p>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-background flex flex-col items-center justify-center z-[100] p-6 overflow-y-auto">
      <div className="max-w-4xl w-full space-y-12 py-12">
        <div className="text-center space-y-4">
          <div className="h-16 w-16 bg-primary/10 rounded-3xl flex items-center justify-center mx-auto mb-6">
            <span className="text-3xl font-bold text-primary">O</span>
          </div>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">Welcome to Odigos</h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Choose a profile to customize how your agent thinks, learns, and communicates with you.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {profiles.map((p) => {
            const Icon = PROFILE_ICONS[p.id] || User
            const isSelected = selecting === p.id

            return (
              <button
                key={p.id}
                disabled={selecting !== null}
                onClick={() => selectProfile(p.id)}
                className={`group relative p-6 rounded-2xl border text-left transition-all duration-300 ${
                  isSelected 
                    ? 'border-primary bg-primary/5 ring-2 ring-primary' 
                    : 'border-border/40 bg-card hover:border-primary/50 hover:bg-muted/50 hover:shadow-lg'
                }`}
              >
                <div className={`h-12 w-12 rounded-xl flex items-center justify-center mb-4 transition-colors ${
                  isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted group-hover:bg-primary/10 group-hover:text-primary'
                }`}>
                  <Icon className="h-6 w-6" />
                </div>
                
                <div className="space-y-1">
                  <h3 className="font-bold text-lg flex items-center gap-2">
                    {p.name}
                    {isSelected && <Check className="h-4 w-4 text-primary" />}
                  </h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {p.description}
                  </p>
                </div>

                {isSelected && (
                  <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-background/20 backdrop-blur-[1px]">
                    <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  </div>
                )}
              </button>
            )
          })}
        </div>

        <p className="text-center text-sm text-muted-foreground pt-4">
          Don't worry, you can always change this later in Settings.
        </p>
      </div>
    </div>
  )
}

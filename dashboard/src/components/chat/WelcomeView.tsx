interface WelcomeViewProps {
  agentName: string
  onSuggest: (text: string) => void
}

export function WelcomeView({ agentName, onSuggest }: WelcomeViewProps) {
  const suggestions = [
    { text: "What can you do?", label: "Capabilities" },
    { text: "Start a journal entry", label: "Journal" },
    { text: "Create a task board for my project", label: "Task Board" },
    { text: "Research the latest trends in AI agents", label: "Research" },
  ]

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center animate-in fade-in zoom-in duration-500">
      <div className="max-w-md space-y-6">
        <div className="space-y-2">
          <div className="h-12 w-12 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <span className="text-2xl font-bold text-primary">{(agentName || 'O')[0]}</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Hello, I'm {agentName}</h1>
          <p className="text-muted-foreground">Your personal AI assistant that learns and improves over time. How can I help you today?</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {suggestions.map((s, i) => (
            <button
              key={s.label}
              onClick={() => onSuggest(s.text)}
              className="p-4 rounded-xl border border-border/40 bg-card hover:border-primary/50 hover:bg-primary/5 transition-all text-left group animate-in fade-in slide-in-from-bottom-3 fill-mode-backwards will-change-transform"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <p className="text-xs font-semibold text-primary mb-1 uppercase tracking-wider">{s.label}</p>
              <p className="text-sm text-muted-foreground group-hover:text-foreground transition-colors">{s.text}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

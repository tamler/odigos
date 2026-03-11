import { Outlet, NavLink } from 'react-router-dom'
import { MessageSquare, Settings } from 'lucide-react'

export default function AppLayout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-14 border-r flex flex-col items-center py-4 gap-4">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `p-2 rounded-lg transition-colors ${isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground'}`
          }
        >
          <MessageSquare className="h-5 w-5" />
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `p-2 rounded-lg transition-colors ${isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground'}`
          }
        >
          <Settings className="h-5 w-5" />
        </NavLink>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}

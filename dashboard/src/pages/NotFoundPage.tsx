import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col items-center justify-center h-full space-y-4">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">The page you're looking for doesn't exist.</p>
      <Button onClick={() => navigate('/')}>Return Home</Button>
    </div>
  )
}

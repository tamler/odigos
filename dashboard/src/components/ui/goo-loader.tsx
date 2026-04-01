import { cn } from '@/lib/utils'

interface GooLoaderProps {
  size?: 'sm' | 'md' | 'lg'
  color?: string
  className?: string
}

const sizes = {
  sm: { container: 120, blob: 12 },
  md: { container: 200, blob: 20 },
  lg: { container: 300, blob: 30 },
}

export function GooLoader({ size = 'md', color, className }: GooLoaderProps) {
  const s = sizes[size]

  return (
    <div className={cn('relative flex items-center justify-center', className)}>
      <div
        className="goo-blobs relative overflow-hidden rounded-[70px]"
        style={{
          width: s.container,
          height: s.container,
          filter: 'url(#goo-filter)',
          transformStyle: 'preserve-3d',
        }}
      >
        <div
          className="goo-blob-center absolute rounded-full"
          style={{
            width: s.blob,
            height: s.blob,
            top: '50%',
            left: '50%',
            transformOrigin: 'left top',
            backgroundColor: color || 'var(--primary)',
            boxShadow: `0 -10px 40px -5px ${color || 'var(--primary)'}`,
          }}
        />
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="goo-blob absolute rounded-full"
            style={{
              width: s.blob,
              height: s.blob,
              top: '50%',
              left: '50%',
              backgroundColor: color || 'var(--primary)',
              animationDelay: `${(i + 1) * 0.2}s`,
            }}
          />
        ))}
      </div>
      <svg xmlns="http://www.w3.org/2000/svg" version="1.1" className="absolute w-0 h-0">
        <defs>
          <filter id="goo-filter">
            <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blur" />
            <feColorMatrix
              in="blur"
              mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7"
              result="goo"
            />
            <feBlend in="SourceGraphic" in2="goo" />
          </filter>
        </defs>
      </svg>
    </div>
  )
}

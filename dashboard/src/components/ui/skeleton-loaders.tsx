import { cn } from "@/lib/utils"

function SkeletonBar({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={cn(
        "rounded-md bg-muted skeleton-shimmer",
        className
      )}
      style={style}
    />
  )
}

export function MessageSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-6 py-6", className)}>
      {/* User message (right) */}
      <div className="flex justify-end gap-3">
        <div className="space-y-2 max-w-[70%]">
          <SkeletonBar className="h-4 w-[80%] ml-auto" />
          <SkeletonBar className="h-4 w-[60%] ml-auto" />
        </div>
        <SkeletonBar className="h-8 w-8 rounded-full shrink-0" />
      </div>

      {/* Assistant message (left) */}
      <div className="flex gap-3">
        <SkeletonBar className="h-8 w-8 rounded-full shrink-0" />
        <div className="space-y-2 max-w-[75%]">
          <SkeletonBar className="h-4 w-[90%]" />
          <SkeletonBar className="h-4 w-[70%]" />
          <SkeletonBar className="h-4 w-[40%]" />
        </div>
      </div>

      {/* User message (right) */}
      <div className="flex justify-end gap-3">
        <div className="space-y-2 max-w-[65%]">
          <SkeletonBar className="h-4 w-[60%] ml-auto" />
        </div>
        <SkeletonBar className="h-8 w-8 rounded-full shrink-0" />
      </div>

      {/* Assistant message (left) */}
      <div className="flex gap-3">
        <SkeletonBar className="h-8 w-8 rounded-full shrink-0" />
        <div className="space-y-2 max-w-[80%]">
          <SkeletonBar className="h-4 w-[85%]" />
          <SkeletonBar className="h-4 w-[65%]" />
          <SkeletonBar className="h-4 w-[50%]" />
          <SkeletonBar className="h-4 w-[30%]" />
        </div>
      </div>
    </div>
  )
}

export function ConversationListSkeleton({ className }: { className?: string }) {
  const rows = [0.85, 0.7, 0.9, 0.65, 0.8, 0.75]

  return (
    <div className={cn("space-y-1 py-2", className)}>
      {rows.map((widthFactor, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2">
          <SkeletonBar className="h-8 w-8 rounded-full shrink-0" />
          <div className="flex-1 space-y-1.5 min-w-0">
            <SkeletonBar className="h-3.5" style={{ width: `${widthFactor * 100}%` }} />
            <SkeletonBar className="h-2.5 w-[60%]" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function ArtifactSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-4", className)}>
      {/* Header bar */}
      <div className="flex items-center gap-3">
        <SkeletonBar className="h-5 w-5 rounded" />
        <SkeletonBar className="h-5 w-[40%]" />
        <div className="ml-auto flex gap-2">
          <SkeletonBar className="h-8 w-8 rounded-lg" />
          <SkeletonBar className="h-8 w-8 rounded-lg" />
        </div>
      </div>
      {/* Content area */}
      <div className="rounded-xl border border-border/40 p-6 space-y-3">
        <SkeletonBar className="h-4 w-[90%]" />
        <SkeletonBar className="h-4 w-[75%]" />
        <SkeletonBar className="h-4 w-[85%]" />
        <SkeletonBar className="h-4 w-[60%]" />
        <SkeletonBar className="h-32 w-full rounded-lg mt-4" />
      </div>
    </div>
  )
}

export function SettingsSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-6 py-4", className)}>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="space-y-2">
          <SkeletonBar className="h-3.5 w-[20%]" />
          <SkeletonBar className="h-10 w-full rounded-lg" />
        </div>
      ))}
      <div className="flex items-center justify-between pt-2">
        <SkeletonBar className="h-3.5 w-[30%]" />
        <SkeletonBar className="h-6 w-11 rounded-full" />
      </div>
    </div>
  )
}

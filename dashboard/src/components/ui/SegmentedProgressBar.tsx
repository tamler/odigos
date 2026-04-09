"use client"

import { cn } from "@/lib/utils"

export interface SegmentedProgressBarProps {
  value: number
  max: number
  segments?: number
  /** Color tone — auto-derived from value/max if not specified */
  tone?: "default" | "warning" | "danger"
  /** Show numeric value next to label */
  showValue?: boolean
  /** Optional label rendered above the bar */
  label?: string
  /** Optional descriptor rendered to the right of the value */
  unit?: string
  size?: "sm" | "md" | "lg"
  className?: string
}

const SIZE_CLASSES = {
  sm: { segment: "h-1", gap: "gap-0.5", label: "text-[10px]" },
  md: { segment: "h-1.5", gap: "gap-0.5", label: "text-xs" },
  lg: { segment: "h-2", gap: "gap-1", label: "text-sm" },
}

const TONE_CLASSES = {
  default: "bg-primary",
  warning: "bg-amber-500 dark:bg-amber-400",
  danger: "bg-red-500 dark:bg-red-400",
}

function deriveTone(ratio: number): "default" | "warning" | "danger" {
  if (ratio >= 0.9) return "danger"
  if (ratio >= 0.75) return "warning"
  return "default"
}

export function SegmentedProgressBar({
  value,
  max,
  segments = 10,
  tone,
  showValue = false,
  label,
  unit,
  size = "md",
  className,
}: SegmentedProgressBarProps) {
  const safeMax = Math.max(max, 1)
  const ratio = Math.max(0, Math.min(1, value / safeMax))
  const filled = Math.round(ratio * segments)
  const resolvedTone = tone ?? deriveTone(ratio)
  const sizeCfg = SIZE_CLASSES[size]
  const filledColor = TONE_CLASSES[resolvedTone]

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {(label || showValue) && (
        <div
          className={cn(
            "flex items-center justify-between text-muted-foreground",
            sizeCfg.label
          )}
        >
          {label && <span className="font-medium">{label}</span>}
          {showValue && (
            <span className="tabular-nums">
              {value}
              {unit ? ` ${unit}` : ""}
              {" / "}
              {max}
              {unit ? ` ${unit}` : ""}
            </span>
          )}
        </div>
      )}
      <div
        className={cn("flex w-full", sizeCfg.gap)}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label}
      >
        {[...Array(segments)].map((_, i) => (
          <div
            key={i}
            className={cn(
              "flex-1 rounded-[1px] transition-colors",
              sizeCfg.segment,
              i < filled ? filledColor : "bg-muted"
            )}
          />
        ))}
      </div>
    </div>
  )
}

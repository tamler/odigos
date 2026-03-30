/**
 * Driver.js integration for guided tours and agent-driven highlighting.
 *
 * The agent can trigger highlights via UI actions, and we can run
 * onboarding tours for new users.
 */
import { useCallback, useRef } from 'react'
import { driver, type DriveStep } from 'driver.js'
import 'driver.js/dist/driver.css'

export function useDriver() {
  const driverRef = useRef<ReturnType<typeof driver> | null>(null)

  const highlight = useCallback((selector: string, title: string, description: string) => {
    if (driverRef.current) driverRef.current.destroy()
    const d = driver({
      animate: true,
      showProgress: false,
      showButtons: ['close'],
      popoverClass: 'odigos-popover',
    })
    driverRef.current = d
    d.highlight({
      element: selector,
      popover: { title, description },
    })
  }, [])

  const tour = useCallback((steps: DriveStep[]) => {
    if (driverRef.current) driverRef.current.destroy()
    const d = driver({
      animate: true,
      showProgress: true,
      showButtons: ['next', 'previous', 'close'],
      popoverClass: 'odigos-popover',
    })
    driverRef.current = d
    d.setSteps(steps)
    d.drive()
  }, [])

  const dismiss = useCallback(() => {
    if (driverRef.current) {
      driverRef.current.destroy()
      driverRef.current = null
    }
  }, [])

  return { highlight, tour, dismiss }
}

/** Default onboarding tour for new users */
export const ONBOARDING_STEPS: DriveStep[] = [
  {
    element: 'textarea',
    popover: {
      title: 'Chat with your agent',
      description: 'Type a message or use voice mode to talk. Your agent remembers everything across conversations.',
    },
  },
  {
    element: '[aria-label="Open menu"]',
    popover: {
      title: 'Navigation',
      description: 'Open the sidebar to access notebooks, kanban boards, images, and settings.',
    },
  },
]

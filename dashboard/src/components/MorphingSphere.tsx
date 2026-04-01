import { useRef, useEffect } from 'react'

// 3D simplex noise (compact implementation)
// Based on Stefan Gustavson's simplex noise
const F3 = 1 / 3, G3 = 1 / 6
const grad3 = [
  [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
  [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
  [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1],
]
const perm = new Uint8Array(512)
const p = [151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180]
for (let i = 0; i < 256; i++) { perm[i] = perm[i + 256] = p[i] }

function noise3d(x: number, y: number, z: number): number {
  const s = (x + y + z) * F3
  const i = Math.floor(x + s), j = Math.floor(y + s), k = Math.floor(z + s)
  const t = (i + j + k) * G3
  const x0 = x - (i - t), y0 = y - (j - t), z0 = z - (k - t)
  let i1: number, j1: number, k1: number, i2: number, j2: number, k2: number
  if (x0 >= y0) {
    if (y0 >= z0) { i1=1;j1=0;k1=0;i2=1;j2=1;k2=0 }
    else if (x0 >= z0) { i1=1;j1=0;k1=0;i2=1;j2=0;k2=1 }
    else { i1=0;j1=0;k1=1;i2=1;j2=0;k2=1 }
  } else {
    if (y0 < z0) { i1=0;j1=0;k1=1;i2=0;j2=1;k2=1 }
    else if (x0 < z0) { i1=0;j1=1;k1=0;i2=0;j2=1;k2=1 }
    else { i1=0;j1=1;k1=0;i2=1;j2=1;k2=0 }
  }
  const x1=x0-i1+G3, y1=y0-j1+G3, z1=z0-k1+G3
  const x2=x0-i2+2*G3, y2=y0-j2+2*G3, z2=z0-k2+2*G3
  const x3=x0-1+3*G3, y3=y0-1+3*G3, z3=z0-1+3*G3
  const ii=i&255, jj=j&255, kk=k&255
  const dot = (g: number[], a: number, b: number, c: number) => g[0]*a + g[1]*b + g[2]*c
  const contrib = (g: number[], d: number, a: number, b: number, c: number) => {
    let t2 = d - a*a - b*b - c*c
    return t2 < 0 ? 0 : (t2 *= t2, t2 * t2 * dot(g, a, b, c))
  }
  return 32 * (
    contrib(grad3[perm[ii+perm[jj+perm[kk]]]%12], 0.6, x0, y0, z0) +
    contrib(grad3[perm[ii+i1+perm[jj+j1+perm[kk+k1]]]%12], 0.6, x1, y1, z1) +
    contrib(grad3[perm[ii+i2+perm[jj+j2+perm[kk+k2]]]%12], 0.6, x2, y2, z2) +
    contrib(grad3[perm[ii+1+perm[jj+1+perm[kk+1]]]%12], 0.6, x3, y3, z3)
  )
}

// Generate sphere points once (icosphere-like distribution)
function generateSpherePoints(count: number): Float32Array {
  const pts = new Float32Array(count * 3)
  // Fibonacci sphere for even distribution
  const phi = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2
    const r = Math.sqrt(1 - y * y)
    const theta = phi * i
    pts[i * 3] = Math.cos(theta) * r
    pts[i * 3 + 1] = y
    pts[i * 3 + 2] = Math.sin(theta) * r
  }
  return pts
}

interface MorphingSphereProps {
  amplitude?: number
  color?: string
  size?: number
  className?: string
}

const PARTICLE_COUNT = 800
const BASE_POINTS = generateSpherePoints(PARTICLE_COUNT)

export function MorphingSphere({
  amplitude = 0,
  color = '#3b82f6',
  size = 280,
  className,
}: MorphingSphereProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const amplitudeRef = useRef(amplitude)
  const animRef = useRef<number>(0)
  const smoothAmpRef = useRef(0.3)
  amplitudeRef.current = amplitude

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = Math.min(window.devicePixelRatio, 2)
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const cx = size / 2
    const cy = size / 2
    const baseRadius = size * 0.28
    const rotationSpeed = 0.2

    // Parse color for gradient use
    const r = parseInt(color.slice(1, 3), 16) || 59
    const g = parseInt(color.slice(3, 5), 16) || 130
    const b = parseInt(color.slice(5, 7), 16) || 246

    const animate = () => {
      animRef.current = requestAnimationFrame(animate)
      const time = performance.now() * 0.001

      // Smooth amplitude interpolation
      const targetAmp = 0.3 + amplitudeRef.current * 0.5
      smoothAmpRef.current += (targetAmp - smoothAmpRef.current) * 0.12

      ctx.clearRect(0, 0, size, size)

      // Rotation angle
      const angle = time * rotationSpeed
      const cosA = Math.cos(angle)
      const sinA = Math.sin(angle)

      // Project and draw each particle
      const projected: { x: number; y: number; z: number; n: number }[] = []

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const ox = BASE_POINTS[i * 3]
        const oy = BASE_POINTS[i * 3 + 1]
        const oz = BASE_POINTS[i * 3 + 2]

        // Noise displacement
        const n = noise3d(
          ox * 0.6 + time * 0.2,
          oy * 0.4 + time * 0.3,
          oz * 0.2 + time * 0.2,
        )
        const disp = 1 + n * smoothAmpRef.current * 0.4

        let px = ox * disp
        let py = oy * disp
        let pz = oz * disp

        // Y-axis rotation
        const rx = px * cosA + pz * sinA
        const rz = -px * sinA + pz * cosA

        projected.push({
          x: cx + rx * baseRadius,
          y: cy + py * baseRadius,
          z: rz,
          n,
        })
      }

      // Sort by z for depth (back to front)
      projected.sort((a, b) => a.z - b.z)

      for (const p of projected) {
        const depth = (p.z + 1.5) / 3 // normalize 0..1
        const particleSize = 1 + depth * 2.5 + p.n * 1.5
        const alpha = 0.15 + depth * 0.7

        ctx.beginPath()
        ctx.arc(p.x, p.y, Math.max(0.5, particleSize), 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`
        ctx.fill()
      }
    }

    animate()

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current)
    }
  }, [size, color])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: size, height: size }}
    />
  )
}

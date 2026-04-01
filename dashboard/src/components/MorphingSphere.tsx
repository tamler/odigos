import { useRef, useEffect, useCallback } from 'react'
import * as THREE from 'three'

const VERTEX_NOISE = `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x*34.0)+10.0)*x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0/6.0, 1.0/3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
    i.z + vec4(0.0, i1.z, i2.z, 1.0))
    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.5 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 105.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}
`

interface MorphingSphereProps {
  amplitude?: number
  color?: string
  size?: number
  className?: string
}

export function MorphingSphere({
  amplitude = 0,
  color = '#3b82f6',
  size = 280,
  className,
}: MorphingSphereProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const stateRef = useRef<{
    renderer?: THREE.WebGLRenderer
    scene?: THREE.Scene
    camera?: THREE.PerspectiveCamera
    material?: THREE.PointsMaterial
    mesh?: THREE.Points
    animId?: number
  }>({})
  const amplitudeRef = useRef(amplitude)
  amplitudeRef.current = amplitude

  const buildScene = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1000)
    camera.position.z = 3

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(size, size)
    container.appendChild(renderer.domElement)

    const geometry = new THREE.IcosahedronGeometry(1, 40)

    // Create dot texture
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 32
    const ctx = canvas.getContext('2d')!
    const circle = new Path2D()
    circle.arc(16, 16, 16, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill(circle)
    const texture = new THREE.CanvasTexture(canvas)

    const material = new THREE.PointsMaterial({
      map: texture,
      blending: THREE.AdditiveBlending,
      color: new THREE.Color(color),
      depthTest: false,
    })

    const baseRadius = 1.5
    const particleSizeMin = 0.01
    const particleSizeMax = 0.08

    material.onBeforeCompile = (shader) => {
      shader.uniforms.time = { value: 0 }
      shader.uniforms.radius = { value: baseRadius }
      shader.uniforms.particleSizeMin = { value: particleSizeMin }
      shader.uniforms.particleSizeMax = { value: particleSizeMax }
      shader.uniforms.amp = { value: 0.4 }
      shader.vertexShader = [
        'uniform float particleSizeMax;',
        'uniform float particleSizeMin;',
        'uniform float radius;',
        'uniform float time;',
        'uniform float amp;',
        VERTEX_NOISE,
        shader.vertexShader,
      ].join('\n')
      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        `
          vec3 p = position;
          float n = snoise(vec3(p.x*0.6 + time*0.2, p.y*0.4 + time*0.3, p.z*0.2 + time*0.2));
          p += n * amp;
          float l = radius / length(p);
          p *= l;
          float s = mix(particleSizeMin, particleSizeMax, n);
          vec3 transformed = vec3(p.x, p.y, p.z);
        `
      )
      shader.vertexShader = shader.vertexShader.replace(
        'gl_PointSize = size;',
        'gl_PointSize = s;'
      )
      material.userData.shader = shader
    }

    const mesh = new THREE.Points(geometry, material)
    scene.add(mesh)

    stateRef.current = { renderer, scene, camera, material, mesh }

    const animate = () => {
      const st = stateRef.current
      if (!st.renderer) return
      st.animId = requestAnimationFrame(animate)
      const time = performance.now() * 0.001
      if (st.mesh) st.mesh.rotation.set(0, time * 0.2, 0)
      if (st.material?.userData.shader) {
        st.material.userData.shader.uniforms.time.value = time
        // Amplitude drives noise displacement: 0.3 at rest, up to 0.8 at full voice
        const targetAmp = 0.3 + amplitudeRef.current * 0.5
        const currentAmp = st.material.userData.shader.uniforms.amp.value
        st.material.userData.shader.uniforms.amp.value += (targetAmp - currentAmp) * 0.15
      }
      st.renderer.render(st.scene!, st.camera!)
    }
    animate()
  }, [size, color])

  useEffect(() => {
    buildScene()
    return () => {
      const st = stateRef.current
      if (st.animId) cancelAnimationFrame(st.animId)
      if (st.renderer) {
        st.renderer.dispose()
        st.renderer.domElement.remove()
      }
      stateRef.current = {}
    }
  }, [buildScene])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: size, height: size }}
    />
  )
}

import { useEffect, useRef } from 'react'
import gsap from 'gsap'

type Kind = 'shell' | 'visor' | 'blue' | 'warm' | 'edge'
type Dot = { x: number; y: number; z: number; ox: number; oy: number; oz: number; vx: number; vy: number; kind: Kind; size: number; phase: number }

const COLORS: Record<Kind, [number, number, number]> = {
  shell: [218, 232, 255],
  visor: [22, 55, 96],
  blue: [67, 145, 255],
  warm: [238, 216, 170],
  edge: [135, 181, 255],
}

const hash = (n: number) => {
  const v = Math.sin(n * 12.9898) * 43758.5453
  return v - Math.floor(v)
}

function dot(dots: Dot[], x: number, y: number, z: number, kind: Kind, size: number, phase: number) {
  dots.push({ x, y, z, ox: x, oy: y, oz: z, vx: 0, vy: 0, kind, size, phase })
}

function roundedOutline(dots: Dot[], x: number, y: number, w: number, h: number, r: number, count: number, kind: Kind, size: number, seed: number) {
  const path: Array<[number, number]> = []
  const arc = (cx: number, cy: number, from: number, to: number) => {
    for (let i = 0; i < 18; i += 1) { const a = from + (to - from) * i / 18; path.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]) }
  }
  for (let i = 0; i < 24; i += 1) path.push([x + r + (w - 2 * r) * i / 23, y])
  arc(x + w - r, y + r, -Math.PI / 2, 0)
  for (let i = 0; i < 24; i += 1) path.push([x + w, y + r + (h - 2 * r) * i / 23])
  arc(x + w - r, y + h - r, 0, Math.PI / 2)
  for (let i = 0; i < 24; i += 1) path.push([x + w - r - (w - 2 * r) * i / 23, y + h])
  arc(x + r, y + h - r, Math.PI / 2, Math.PI)
  for (let i = 0; i < 24; i += 1) path.push([x, y + h - r - (h - 2 * r) * i / 23])
  arc(x + r, y + r, Math.PI, Math.PI * 1.5)
  for (let i = 0; i < count; i += 1) { const p = path[Math.floor(i * path.length / count) % path.length]; dot(dots, p[0], p[1], (hash(seed + i) - .5) * 22, kind, size + hash(seed + i * 2) * .8, seed + i) }
}

function fillRounded(dots: Dot[], x: number, y: number, w: number, h: number, count: number, kind: Kind, seed: number, depth: number) {
  let i = 0
  let attempt = 0
  while (i < count && attempt < count * 10) {
    attempt += 1
    const px = x + hash(seed + attempt * 1.71) * w
    const py = y + hash(seed + attempt * 3.19) * h
    const nx = Math.abs(px - (x + w / 2)) / (w / 2)
    const ny = Math.abs(py - (y + h / 2)) / (h / 2)
    const corner = nx > .72 && ny > .68
    if (corner && Math.hypot((nx - .72) / .28, (ny - .68) / .32) > 1) continue
    dot(dots, px, py, (hash(seed + attempt * 4.4) - .5) * depth, kind, .8 + hash(seed + attempt * 5.4) * 1.35, seed + attempt)
    i += 1
  }
}

function ellipse(dots: Dot[], cx: number, cy: number, rx: number, ry: number, count: number, kind: Kind, seed: number, depth = 18) {
  for (let i = 0; i < count; i += 1) { const a = Math.PI * 2 * i / count; dot(dots, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, (hash(seed + i) - .5) * depth, kind, 1.2 + hash(seed + i * 2) * 1.2, seed + i) }
}

export function HeroKnot({ center = false }: { center?: boolean }) {
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const host = root.current
    const canvasEl = canvas.current
    if (!host || !canvasEl) return
    const ctx = canvasEl.getContext('2d')
    if (!ctx) return
    let width = 0, height = 0, scale = 1, time = 0
    let pointerX = Number.NaN, pointerY = Number.NaN
    let dots: Dot[] = []
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = host.clientWidth; height = host.clientHeight; scale = Math.min(width, height) / 520
      canvasEl.width = Math.round(width * dpr); canvasEl.height = Math.round(height * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const cx = width / 2, cy = height / 2, s = scale, next: Dot[] = []
      roundedOutline(next, cx - 145 * s, cy - 105 * s, 290 * s, 235 * s, 70 * s, 360, 'shell', 1.55, 10)
      fillRounded(next, cx - 142 * s, cy - 102 * s, 284 * s, 229 * s, 300, 'shell', 20, 42 * s)
      roundedOutline(next, cx - 105 * s, cy - 4 * s, 210 * s, 84 * s, 36 * s, 260, 'edge', 1.45, 30)
      fillRounded(next, cx - 103 * s, cy - 2 * s, 206 * s, 80 * s, 250, 'visor', 40, 22 * s)
      ellipse(next, cx - 168 * s, cy + 14 * s, 31 * s, 52 * s, 80, 'edge', 50, 24 * s)
      ellipse(next, cx + 168 * s, cy + 14 * s, 31 * s, 52 * s, 80, 'edge', 60, 24 * s)
      for (let i = 0; i < 34; i += 1) dot(next, cx + (hash(i) - .5) * 3 * s, cy - (160 - i * 1.7) * s, (hash(i + 80) - .5) * 16, 'edge', 1.5, i)
      // Match the official website icon: forehead check seal + blue antenna.
      ellipse(next, cx, cy - 54 * s, 34 * s, 34 * s, 92, 'edge', 110, 8 * s)
      for (let i = 0; i < 34; i += 1) {
        const t = i / 33
        const x = t < .42 ? -17 + t / .42 * 17 : 0 + (t - .42) / .58 * 29
        const y = t < .42 ? -54 + t / .42 * 17 : -37 - (t - .42) / .58 * 31
        dot(next, cx + x * s, cy + y * s, .3, 'blue', 1.8, 130 + i)
      }
      ellipse(next, cx, cy - 177 * s, 18 * s, 18 * s, 70, 'blue', 70, 14 * s)
      ellipse(next, cx - 39 * s, cy + 35 * s, 15 * s, 9 * s, 48, 'blue', 80, 10 * s)
      ellipse(next, cx + 39 * s, cy + 35 * s, 15 * s, 9 * s, 48, 'blue', 90, 10 * s)
      for (let i = 0; i < 24; i += 1) dot(next, cx + (-28 + 23 * i / 23) * s, cy + (-50 + 22 * i / 23) * s, .12, 'warm', 1.8, i)
      for (let i = 0; i < 36; i += 1) dot(next, cx + (-5 + 40 * i / 35) * s, cy + (-28 - 40 * i / 35) * s, .2, 'blue', 1.8, i + 40)
      dots = next
    }
    const pointer = (event: PointerEvent) => { const r = host.getBoundingClientRect(); pointerX = event.clientX - r.left; pointerY = event.clientY - r.top }
    const draw = () => {
      time += .012
      ctx.clearRect(0, 0, width, height)
      const cx = width / 2, cy = height / 2, hasPointer = Number.isFinite(pointerX) && Number.isFinite(pointerY)
      const yaw = Math.sin(time * .55) * .12 + (hasPointer ? (pointerX / width - .5) * .08 : 0)
      const pitch = Math.cos(time * .43) * .025 + (hasPointer ? (pointerY / height - .5) * .06 : 0)
      const cyaw = Math.cos(yaw), syaw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
      const rendered = dots.map((d) => {
        const bobX = d.ox + Math.sin(time + d.phase) * .18 * scale
        const bobY = d.oy + Math.cos(time * .8 + d.phase) * .16 * scale
        const dx = d.x - pointerX, dy = d.y - pointerY, distance = Math.hypot(dx, dy)
        if (hasPointer && distance < 72 * scale && distance > .1) { const force = (1 - distance / (72 * scale)) * 1.15; d.vx += dx / distance * force; d.vy += dy / distance * force }
        d.vx += (bobX - d.x) * .055; d.vy += (bobY - d.y) * .055; d.vx *= .86; d.vy *= .86; d.x += d.vx; d.y += d.vy
        const localX = d.x - cx
        const localY = d.y - cy
        const x = localX * cyaw - d.z * syaw
        const z1 = localX * syaw + d.z * cyaw
        const y = localY * cp - z1 * sp
        const z = z1 * cp + localY * sp
        const p = 1 / (1.72 - z / Math.max(1, 180 * scale))
        return { d, x: cx + x * p, y: cy + y * p, z }
      }).sort((a, b) => a.z - b.z)
      ctx.globalCompositeOperation = 'screen'
      for (const item of rendered) { const [r, g, b] = COLORS[item.d.kind]; const front = Math.max(0, Math.min(1, .4 + item.z / (4 * scale))); const alpha = item.d.kind === 'visor' ? .18 + front * .26 : .28 + front * .66; const size = item.d.size * (.7 + front * .95); ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`; ctx.fillRect(item.x - size / 2, item.y - size / 2, size, size) }
      ctx.globalCompositeOperation = 'source-over'
      ctx.save(); ctx.translate(cx, cy); ctx.scale(1 + Math.sin(time * .7) * .008, 1 + Math.sin(time * .7) * .008)
      ctx.beginPath(); ctx.roundRect(-145 * scale, -105 * scale, 290 * scale, 235 * scale, 70 * scale); ctx.fillStyle = 'rgba(180,215,255,.012)'; ctx.fill(); ctx.strokeStyle = 'rgba(190,225,255,.045)'; ctx.lineWidth = 1.1 * scale; ctx.stroke()
      ctx.beginPath(); ctx.roundRect(-105 * scale, -4 * scale, 210 * scale, 84 * scale, 36 * scale); const v = ctx.createLinearGradient(-105 * scale, -4 * scale, 105 * scale, 80 * scale); v.addColorStop(0, 'rgba(13,34,65,.18)'); v.addColorStop(.5, 'rgba(46,103,173,.10)'); v.addColorStop(1, 'rgba(8,22,45,.22)'); ctx.fillStyle = v; ctx.fill(); ctx.strokeStyle = 'rgba(108,177,255,.08)'; ctx.stroke(); ctx.restore()
      const pulse = .62 + Math.sin(time * 1.4) * .18; ctx.shadowColor = 'rgba(73,145,255,.9)'; ctx.shadowBlur = 10 * scale; ctx.fillStyle = `rgba(73,145,255,${pulse})`; ctx.beginPath(); ctx.ellipse(cx - 39 * scale, cy + 35 * scale, 15 * scale, 9 * scale, 0, 0, Math.PI * 2); ctx.fill(); ctx.beginPath(); ctx.ellipse(cx + 39 * scale, cy + 35 * scale, 15 * scale, 9 * scale, 0, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0
      const glow = ctx.createRadialGradient(cx, cy, 4, cx, cy, 225 * scale); glow.addColorStop(0, 'rgba(67,145,255,.13)'); glow.addColorStop(.55, 'rgba(67,145,255,.04)'); glow.addColorStop(1, 'rgba(67,145,255,0)'); ctx.fillStyle = glow; ctx.fillRect(0, 0, width, height)
    }
    resize(); window.addEventListener('resize', resize); window.addEventListener('pointermove', pointer, { passive: true }); gsap.ticker.add(draw)
    return () => { gsap.ticker.remove(draw); window.removeEventListener('resize', resize); window.removeEventListener('pointermove', pointer) }
  }, [])
  return <div ref={root} className={`robot-hero ${center ? 'robot-hero-center' : ''}`} aria-hidden="true"><canvas ref={canvas} /></div>
}



